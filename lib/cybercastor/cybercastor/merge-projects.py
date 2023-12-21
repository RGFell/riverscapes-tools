"""
Demo script to download files from Data Exchange
"""
from typing import Dict, List, Tuple
from datetime import datetime
import sys
import os
import subprocess
import json
import argparse
from osgeo import ogr
import semantic_version
from osgeo import ogr, osr
from rscommons import dotenv, Logger
from cybercastor.classes.RiverscapesAPI import RiverscapesAPI
from rscommons.util import safe_makedirs
import xml.etree.ElementTree as ET
from rsxml.project_xml import (
    Project,
    MetaData,
    Meta,
    MetaValue,
    ProjectBounds,
    Coords,
    BoundingBox,
    Dataset,
    GeoPackageDatasetTypes,
    Realization,
)


def search_projects(riverscapes_api, project_type: str, project_tags: List[str]) -> List[str]:

    search_params = {
        'projectTypeId': project_type,
        # 'meta': [{'key': 'ModelVersion', 'value': '1234'}],
        'tags': project_tags
    }

    project_limit = 500
    project_offset = 0
    total = 0
    projects = []
    while project_offset == 0 or project_offset < total:
        results = riverscapes_api.run_query(riverscapes_api.load_query('searchProjects'), {'searchParams': search_params, 'limit': project_limit, 'offset': project_offset})
        total = results['data']['searchProjects']['total']
        project_offset += project_limit

        projects += [project['item']for project in results['data']['searchProjects']['results']]

    return projects

    # if len(projects) == 0:
    #     return None
    # elif len(projects) == 1:
    #     return projects[list(projects.keys())[0]]
    # else:
    #     # Find the model with the greatest version number
    #     project_versions = {}
    #     for project_id, project_info in projects.items():
    #         for key, val in {meta_item['key']: meta_item['value'] for meta_item in project_info['meta']}.items():
    #             if key.replace(' ', '').lower() == 'modelversion' and val is not None:
    #                 project_versions[semantic_version.Version(val)] = project_id
    #                 break

    #     project_versions_list = list(project_versions)
    #     project_versions_list.sort(reverse=True)
    #     return projects[project_versions[project_versions_list[0]]]


def download_project(riverscapes_api, output_folder, project_id: str, force_download: bool) -> List[str]:

    # Build a dictionary of files in the project keyed by local path to downloadUrl
    files_query = riverscapes_api.load_query('projectFiles')
    file_results = riverscapes_api.run_query(files_query, {"projectId": project_id})
    files = {file['localPath']: file for file in file_results['data']['project']['files']}

    project_file_path = None
    for rel_path, file in files.items():
        download_path = os.path.join(output_folder, project_id, rel_path)

        if os.path.isfile(download_path):
            if not force_download:
                continue
            os.remove(download_path)

        safe_makedirs(os.path.dirname(download_path))
        riverscapes_api.download_file(file, download_path, True)

        if rel_path.endswith('project.rs.xml'):
            project_file_path = download_path

    return project_file_path


def merge_projects(projects: List[str], output_dir: str, name: str) -> None:

    log = Logger()
    log.info(f'Merging {len(projects)} project(s)')

    project_rasters = {}
    project_vectors = {}
    bounds_geojson_files = []
    for project in projects:
        get_raster_datasets(project, project_rasters)
        get_vector_datasets(project, project_vectors)
        get_bounds_geojson_file(project, bounds_geojson_files)

    # process_rasters(project_rasters, output_dir)
    # process_vectors(project_vectors, output_dir)

    # build union of project bounds
    output_bounds_path = os.path.join(output_dir, 'project_bounds.geojson')
    centroid, bounding_rect = union_polygons(bounds_geojson_files, output_bounds_path)

    # Generate a new project.rs.xml file for the merged project based
    # on the first project in the list
    merge_project = Project.load_project(projects[0])
    merge_project.name = name
    # merge_project.meta_data.add_meta(Meta('Date Created', str(datetime.now().isoformat()), type='isodate'), ext=None)

    coords = Coords(centroid[0], centroid[1])
    bounding_box = BoundingBox(bounding_rect[0], bounding_rect[1], bounding_rect[2], bounding_rect[3])
    merge_project.bounds = ProjectBounds(coords, bounding_box, os.path.basename(output_bounds_path))

    # Remove the project level metadata
    # for key in merge_project.meta_data.get_meta_keys():
    #     merge_project.meta_data.remove_meta(key)

    merge_project.meta_data = MetaData()

    merge_project.write(os.path.join(output_dir, 'project.rs.xml'))


def union_polygons(input_geojson_files, output_geojson_file) -> Tuple[str, str]:

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

    # Get centroid coordinates
    centroid = union_result.Centroid().GetPoint()

    # Get bounding rectangle coordinates (min_x, max_x, min_y, max_y)
    bounding_rect = union_result.GetEnvelope()

    # Create a new GeoJSON file for the union result
    output_driver = ogr.GetDriverByName('GeoJSON')
    output_ds = output_driver.CreateDataSource(output_geojson_file)
    output_layer = output_ds.CreateLayer('union', geom_type=ogr.wkbPolygon)

    # Create a feature and set the geometry for the union result
    feature_defn = output_layer.GetLayerDefn()
    feature = ogr.Feature(feature_defn)
    feature.SetGeometry(union_result)

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


def get_vector_datasets(project_xml_path: str, master_project: Dict) -> None:
    """
    Discover all the vector datasets in the project.rs.xml file and incorporate them
    intro the master project dictionary.
    project: str - Path to the project.rs.xml file
    master_project: Dict - The master list of GeoPackages and feature classes
    """

    tree = ET.parse(project_xml_path)
    # find each geopackage in the project
    for geopackage in tree.findall('.//Geopackage'):
        gpkg_id = geopackage.attrib['id']
        path = geopackage.find('Path').text
        name = geopackage.find('Name').text

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

    for gpkg_info in master_project.values():

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
                cmd = f'ogr2ogr -f GPKG -makevalid -append  -nln {feature_class} {output_gpkg_file} {input_gpkg_file} {feature_class}'
                subprocess.call([cmd], shell=True, cwd=output_gpkg_dir)


def process_rasters(master_project: Dict, output_dir: str) -> None:
    """
    Process the raster datasets in the master project dictionary.  This will
    merge all occurances of each type of raster into a single raster for each type.
    master_project: Dict - The master list of rasters in the project
    output_dir: str - The top level output directory
    """

    for raster_info in master_project.values():

        raster_path = os.path.join(output_dir, raster_info['path'])
        safe_makedirs(os.path.dirname(raster_path))

        input_rasters = [rp['path'] for rp in raster_info['occurences']]
        gdal_merge = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv', 'bin', 'gdal_merge.py')
        params = ['python', gdal_merge, '-o', raster_path, '-co', 'COMPRESS=LZW'] + input_rasters
        print(params)
        subprocess.call(params, shell=False)


def get_raster_datasets(project, master_project) -> None:
    """
    Discover all the rasters in the project.rs.xml file and incorporate them
    intro the master project dictionary.
    project: str - Path to the project.rs.xml file
    master_project: Dict - The master list of rasters across all projects
    """

    tree = ET.parse(project)
    for raster in tree.findall('.//Raster'):
        raster_id = raster.attrib['id']
        path = raster.find('Path').text
        name = raster.find('Name').text
        if id not in master_project:
            master_project[id] = {'path': path, 'name': name, 'id': raster_id, 'occurences': []}
        master_project[id]['occurences'].append({'path': os.path.join(os.path.dirname(project), path)})


def main():
    """
    Merge projects
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('environment', help='Riverscapes stage', type=str, default='production')
    parser.add_argument('output_folder', help='top level output folder', type=str)
    parser.add_argument('project_type', help='project type', type=str)
    parser.add_argument('project_tags', help='Comma separated list of Data Exchange tags', type=str)
    parser.add_argument('name', help='Output project name', type=str)
    args = dotenv.parse_args_env(parser)

    riverscapes_api = RiverscapesAPI(stage=args.environment)
    if riverscapes_api.accessToken is None:
        riverscapes_api.refresh_token()

    projects = search_projects(riverscapes_api, args.project_type, args.project_tags.split(','))

    for project in projects:
        project_id = project['id']
        project_local = download_project(riverscapes_api, args.output_folder, project_id, False)
        project['localPath'] = project_local

    merge_projects(projects, args.output_folder, args.name)

    sys.exit(0)


if __name__ == '__main__':
    main()
