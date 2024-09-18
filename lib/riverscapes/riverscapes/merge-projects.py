"""
Merge projects within a collection into a single collection.

Example file regex list: .*brat\.gpkg|.*brat\.html

Note:
- period then star matches any characters at the start of the string.
- periods in the actual string need to be escaped with a backslash.
- the pipe character is used to separate the regexes.
"""
from typing import Dict, Tuple, List
from datetime import datetime
import re
import sys
import os
import logging
import subprocess
import json
import argparse
import xml.etree.ElementTree as ET
from osgeo import gdal, ogr
import inquirer
from rsxml import dotenv, Logger, safe_makedirs
from rsxml.project_xml import (
    Project,
    MetaData,
    Meta,
    ProjectBounds,
    Coords,
    BoundingBox,
)
from rscommons import Raster
from riverscapes import RiverscapesAPI, RiverscapesProject, RiverscapesSearchParams

name_lookup = {'RSContext': "RS Context",
               'ChannelArea': "Channel Area",
               'TauDEM': "TauDEM",
               'VBET': "VBET",
               'BRAT': "BRAT",
               'anthro': "ANTHRO",
               'rcat': "RCAT",
               'rs_metric_engine': "Metric Engine"}


def merge_projects(projects_lookup: Dict[str, RiverscapesProject], merged_dir: str, name: str, project_type: str, collection_id: str, rs_stage: str, regex_list: List[str], delete_source: bool = False) -> None:
    """
    Merge the projects in the projects_lookup dictionary into a single project
    """

    log = Logger('Merging')
    log.info(f'Merging {len(projects_lookup)} project(s)')

    project_rasters = {}
    project_vectors = {}
    bounds_geojson_files = []

    first_project_xml = None
    for proj_path, project in projects_lookup.items():

        project_xml = os.path.join(proj_path, 'project.rs.xml')
        if project_xml is None:
            log.warning(f'Skipping project with no project.rs.xml file {project["id"]}')
            continue
        first_project_xml = project_xml

        get_raster_datasets(project_xml, project_rasters, regex_list)
        get_vector_datasets(project_xml, project_vectors, regex_list)
        get_bounds_geojson_file(project_xml, bounds_geojson_files)

    process_rasters(project_rasters, merged_dir, delete_source=delete_source)
    process_vectors(project_vectors, merged_dir)

    # build union of project bounds
    output_bounds_path = os.path.join(merged_dir, 'project_bounds.geojson')
    centroid, bounding_rect = union_polygons(bounds_geojson_files, output_bounds_path)

    # Generate a new project.rs.xml file for the merged project based
    # on the first project in the list
    merge_project = Project.load_project(first_project_xml)
    merge_project.name = name

    merge_project.description = f"""This project was generated by merging {len(projects_lookup)} {project_type} projects together,
            using the merge-projects.py script.  The project bounds are the union of the bounds of the
            individual projects."""

    coords = Coords(centroid[0], centroid[1])
    bounding_box = BoundingBox(bounding_rect[0], bounding_rect[2], bounding_rect[1], bounding_rect[3])
    merge_project.bounds = ProjectBounds(coords, bounding_box, os.path.basename(output_bounds_path))

    project_urls = [f'https://{"staging." if rs_stage == "STAGING" else ""}data.riverscapes.net/p/{project.id}' for proj_path, project in projects_lookup.items()]

    merge_project.meta_data = MetaData([Meta('projects', json.dumps(project_urls), 'json', None)])
    merge_project.meta_data.add_meta('Date Created', str(datetime.now().isoformat()), meta_type='isodate', ext=None)
    merge_project.meta_data.add_meta('Collection ID', collection_id)
    merge_project.warehouse = None

    merged_project_xml = os.path.join(merged_dir, 'project.rs.xml')
    merge_project.write(merged_project_xml)
    replace_log_file(merged_project_xml)
    delete_unmerged_paths(merged_project_xml)
    log.info(f'Merged project.rs.xml file written to {merged_project_xml}')


def delete_unmerged_paths(merged_project_xml):
    """
    Reports, ShapeFiles and logs are not included in the merge.
    Look for all elements called <Path> and remove their parents
    """
    log = Logger('Delete')

    # Load the XML file and search for any tag called Path
    tree = ET.parse(merged_project_xml)

    # create a dictionary that maps from each element to its parent
    root = tree.getroot()
    parent_map = {c: p for p in root.iter() for c in p}

    for path_element in tree.findall('.//Path'):
        file_ext = ['gpkg', 'geojson', 'tif', 'tiff', 'log']
        matches = [ext for ext in file_ext if path_element.text.lower().endswith(ext)]
        if len(matches) == 0:
            log.info(f'Removing non GeoPackage, raster or log with contents {path_element.text}')
            # Get and remove the parent of the Path element
            parent = parent_map[path_element]
            grandparent = parent_map[parent]
            grandparent.remove(parent)

    tree.write(merged_project_xml)


def replace_log_file(merged_project_xml) -> None:
    """
    Load the merged project.rs.xml and search for all occurences
    of a log file and replace them with the merged log file
    """

    log = Logger('Log')

    tree = ET.parse(merged_project_xml)
    for log_file in tree.findall('.//LogFile/Path'):
        log_file.text = os.path.basename(log.instance.logpath)
    tree.write(merged_project_xml)


def union_polygons(input_geojson_files, output_geojson_file) -> Tuple[str, str]:
    """_summary_

    Args:
        input_geojson_files (_type_): _description_
        output_geojson_file (_type_): _description_

    Returns:
        Tuple[str, str]: _description_
    """

    # Create a new OGR memory data source
    mem_driver = ogr.GetDriverByName('Memory')
    mem_ds = mem_driver.CreateDataSource('')

    # Create a new layer in the memory data source
    mem_layer = mem_ds.CreateLayer('union', geom_type=ogr.wkbPolygon)

    # Iterate over input GeoJSON files
    for input_file in input_geojson_files:
        # Open the GeoJSON file
        with open(input_file, 'r', encoding='utf8') as file:
            geojson_data = json.load(file)

        # Create an OGR feature and set its geometry

        # Extract coordinates from the GeoJSON structure
        coordinates = geojson_data['features'][0]['geometry']['coordinates']

        # Create an OGR feature and set its geometry
        feature_defn = mem_layer.GetLayerDefn()
        feature = ogr.Feature(feature_defn)
        geometry = ogr.CreateGeometryFromJson(json.dumps({
            "type": "Polygon",
            "coordinates": coordinates
        }))
        feature.SetGeometry(geometry)

        # Add the feature to the layer
        mem_layer.CreateFeature(feature)

    # Perform the union operation on the layer
    union_result = None
    for feature in mem_layer:
        if union_result is None:
            union_result = feature.GetGeometryRef().Clone()
        else:
            union_result = union_result.Union(feature.GetGeometryRef())

    # Remove any donuts (typically slivers caused by rounding the individual Polygon extents)
    clean_polygon = ogr.Geometry(ogr.wkbPolygon)
    ring = union_result.GetGeometryRef(0)
    clean_polygon.AddGeometry(ring)

    # Get centroid coordinates
    centroid = clean_polygon.Centroid().GetPoint()

    # Get bounding rectangle coordinates (min_x, max_x, min_y, max_y)
    bounding_rect = clean_polygon.GetEnvelope()

    # Create a new GeoJSON file for the union result
    output_driver = ogr.GetDriverByName('GeoJSON')
    output_ds = output_driver.CreateDataSource(output_geojson_file)
    output_layer = output_ds.CreateLayer('union', geom_type=ogr.wkbPolygon)

    # Create a feature and set the geometry for the union result
    feature_defn = output_layer.GetLayerDefn()
    feature = ogr.Feature(feature_defn)
    feature.SetGeometry(clean_polygon)

    # Add the feature to the output layer
    output_layer.CreateFeature(feature)

    # Clean up resources
    mem_ds = None
    output_ds = None

    return centroid, bounding_rect


def get_bounds_geojson_file(project_xml_path: str, bounds_files):
    """
    Get the GeoJSON file for the project bounds
    project_xml_path: str - Path to the project.rs.xml file
    bounds_files: List - List of GeoJSON files
    """

    tree = ET.parse(project_xml_path)
    rel_path = tree.find('.//ProjectBounds/Path').text
    abs_path = os.path.join(os.path.dirname(project_xml_path), rel_path)
    if os.path.isfile(abs_path):
        bounds_files.append(abs_path)


def get_vector_datasets(project_xml_path: str, master_project: Dict, regex_list) -> None:
    """
    Discover all the vector datasets in the project.rs.xml file and incorporate them
    intro the master project dictionary.
    project: str - Path to the project.rs.xml file
    master_project: Dict - The master list of GeoPackages and feature classes
    """

    log = Logger('Vectors')

    tree = ET.parse(project_xml_path)
    # find each geopackage in the project
    for geopackage in tree.findall('.//Geopackage'):
        gpkg_id = geopackage.attrib['id']
        path = geopackage.find('Path').text
        name = geopackage.find('Name').text

        if not any([re.compile(x, re.IGNORECASE).match(path) for x in regex_list]):
            log.info(f'Skipping non-regex raster {name} with path {path}')
            continue

        if (gpkg_id not in master_project):
            master_project[gpkg_id] = {'rel_path': path, 'abs_path': os.path.join(os.path.dirname(project_xml_path), path), 'name': name, 'id': gpkg_id, 'layers': {}}

        # find each layer in the geopackage
        for layer in geopackage.findall('.//Vector'):
            fc_name = layer.attrib['lyrName']
            layer_name = layer.find('Name').text

            if fc_name not in master_project[gpkg_id]['layers']:
                master_project[gpkg_id]['layers'][fc_name] = {'fc_name': fc_name, 'name': layer_name, 'occurences': []}

            master_project[gpkg_id]['layers'][fc_name]['occurences'].append({'path': os.path.join(os.path.dirname(project_xml_path), path)})


def process_vectors(master_project: Dict, output_dir: str) -> None:
    """
    Process the vector datasets in the master project dictionary.  This will
    merge all the vector datasets within each GeoPackage into new GeoPackages
    in the output directory.
    master_project: Dict - The master list of GeoPackages and feature classes
    output_dir: str - The top level output directory
    """

    log = Logger('Vectors')

    for gpkg_info in master_project.values():
        log.info(f'Processing {gpkg_info["name"]} GeoPackage at {gpkg_info["rel_path"]} with {len(gpkg_info["layers"])} layers.')

        # output GeoPackage
        output_gpkg = os.path.join(output_dir, gpkg_info['rel_path'])
        output_gpkg_file = os.path.basename(output_gpkg)
        output_gpkg_dir = os.path.dirname(output_gpkg)
        safe_makedirs(output_gpkg_dir)

        if os.path.isfile(output_gpkg):
            os.remove(output_gpkg)

        for feature_class, feature_class_info in gpkg_info['layers'].items():

            for input_gpkg in feature_class_info['occurences']:
                input_gpkg_file = input_gpkg['path']

                # -nlt {geometry_type}
                input_gpkg_file = input_gpkg['path']
                cmd = f'ogr2ogr -f GPKG -makevalid -append  -nln {feature_class} "{output_gpkg_file}" "{input_gpkg_file}" {feature_class}'
                log.debug(f'EXECUTING: {cmd}')
                subprocess.call([cmd], shell=True, cwd=output_gpkg_dir)


def process_rasters(master_project: Dict, output_dir: str, delete_source: bool = False) -> None:
    """
    Process the raster datasets in the master project dictionary.  This will
    merge all occurances of each type of raster into a single raster for each type.
    master_project: Dict - The master list of rasters in the project
    output_dir: str - The top level output directory
    """

    log = Logger('Rasters')

    for raster_info in master_project.values():
        log.info(f'Merging {len(raster_info["occurences"])} {raster_info["name"]} rasters.')

        output_raster_path = os.path.join(output_dir, raster_info['path'])
        safe_makedirs(os.path.dirname(output_raster_path))

        raster = Raster(raster_info['occurences'][0]['path'])
        integer_raster_enums = [gdal.GDT_Byte, gdal.GDT_UInt16, gdal.GDT_UInt32, gdal.GDT_Int16, gdal.GDT_Int32]
        compression = f'COMPRESS={"DEFLATE" if raster.dataType in integer_raster_enums else "LZW"}'
        no_data = f'-a_nodata {raster.nodata}' if raster.nodata is not None else ''

        input_rasters = [f"\"{rp['path']}\"" for rp in raster_info['occurences']]

        params = ['gdal_merge.py', '-o', f'"{output_raster_path}"', '-co', compression, no_data] + input_rasters
        params_flat = ' '.join(params)
        log.debug(f'EXECUTING: {params_flat}')
        subprocess.call(params_flat, shell=True)

        # Delete the source rasters to free up space
        if delete_source is True:
            for raster_path in input_rasters:
                raster_path = raster_path[1:-1]  # remove the extra quotes
                if os.path.isfile(raster_path):
                    log.info(f'Deleting source raster {raster_path}')
                    os.remove(raster_path)


def get_raster_datasets(project, master_project, regex_list: List[str]) -> None:
    """
    Discover all the rasters in the project.rs.xml file and incorporate them
    intro the master project dictionary. If their path matches the regex_list
    project: str - Path to the project.rs.xml file
    master_project: Dict - The master list of rasters across all projects
    """

    log = Logger('Rasters')

    tree = ET.parse(project)
    rasters = tree.findall('.//Raster') + tree.findall('.//DEM')
    for raster in rasters:
        raster_id = raster.attrib['id']
        path = raster.find('Path').text
        name = raster.find('Name').text

        if not any([re.compile(x, re.IGNORECASE).match(path) for x in regex_list]):
            log.info(f'Skipping non-regex raster {name} with path {path}')
            continue

        if raster_id not in master_project:
            master_project[raster_id] = {'path': path, 'name': name, 'id': raster_id, 'occurences': []}
        master_project[raster_id]['occurences'].append({'path': os.path.join(os.path.dirname(project), path)})


def main():
    """
    Merge projects
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('working_folder', help='top level folder for downloads and output', type=str)
    args = dotenv.parse_args_env(parser)

    default_file_regex = r'.*'

    with RiverscapesAPI() as api:
        project_types = api.get_project_types()
        questions = [
            inquirer.Text('collection_id', message="Enter a valid Collection ID", default="e93450e5-68bf-4c43-bca0-6a6995bd06ad"),
            inquirer.Text('output_name', message="Enter the name for this project", default="test"),
            # Choose a project type from a list of available project types
            inquirer.List('project_type', message="Choose a project type", choices=project_types.keys(), default='BRAT'),
            inquirer.Confirm('delete_source', message="Delete source files after merging?", default=False),
            # example: .*brat\.gpkg|.*brat\.html
            inquirer.Text('file_regex_list', message='List of file regexes to download. Separate with Pipe (|)', default=default_file_regex),
        ]
        answers = inquirer.prompt(questions)

        output_name = f"{answers['output_name']} Merged {name_lookup.get(answers['project_type'], answers['project_type'])}"

        # Parse the file regex list separated by pipes.
        file_regex_list = answers['file_regex_list'].split('|') if answers['file_regex_list'] != default_file_regex and answers['file_regex_list'] != '' else []

        # Always include files used by the merge process: project xml, any logs and bounds GeoJSON
        file_regex_list.append(r'project\.rs\.xml')
        file_regex_list.append(r'project_bounds\.geojson')
        file_regex_list.append(r'.*\.log')

        # Set up some reasonable folders to store things
        working_folder = os.path.join(args.working_folder, output_name)
        download_folder = os.path.join(working_folder, 'downloads')
        merged_folder = os.path.join(working_folder, 'merged')

        safe_makedirs(merged_folder)
        log = Logger('Setup')
        # Put the log in the merged folder so it gets uploaded with the project
        log.setup(log_path=os.path.join(merged_folder, 'merge-projects.log'), log_level=logging.DEBUG)

        # First, find the projects to merge using the Riverscapes API search
        search_params = RiverscapesSearchParams({
            'collection':  answers['collection_id'],
            'projectTypeId': answers['project_type'],
        })

        projects_lookup: Dict[str, RiverscapesProject] = {}
        for project, _stats, search_total in api.search(search_params, progress_bar=True):
            if search_total < 2:
                log.error(f'Insufficient number of projects ({search_total}) found with type {args.project_type} and tags {args.project_tags}. 2 or more needed.')
                sys.exit(1)

            download_path = os.path.join(download_folder, project.id)
            api.download_files(project.id, download_path, file_regex_list)
            projects_lookup[download_path] = project

        delete_source = answers['delete_source']

        merge_projects(projects_lookup, merged_folder, output_name, answers['project_type'], answers['collection_id'], api.stage, file_regex_list, delete_source=delete_source)

    log.info('Process complete')


if __name__ == '__main__':
    main()
