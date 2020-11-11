import argparse
import sqlite3
import os
from xml.etree import ElementTree as ET

from rscommons import Logger, dotenv, ModelConfig, RSReport, RSProject
from rscommons.util import safe_makedirs, sizeof_fmt
from rscommons.plotting import xyscatter, box_plot

from vbet.__version__ import __version__


class VBETReport(RSReport):

    def __init__(self, report_path, rs_project, project_root):
        super().__init__(rs_project, report_path)
        self.log = Logger('VBET Report')
        self.project_root = project_root
        self.report_intro()

    def report_intro(self):
        realization = self.xml_project.XMLBuilder.find('Realizations').find('VBET')

        section_in = self.section('Inputs', 'Inputs')
        inputs = list(realization.find('Inputs'))
        [self.layerprint(lyr, section_in, self.project_root) for lyr in inputs if lyr.tag in ['DEM', 'Raster', 'Vector']]

        section_inter = self.section('Intermediates', 'Intermediates')
        intermediates = list(realization.find('Intermediates'))
        [self.layerprint(lyr, section_inter, self.project_root) for lyr in intermediates if lyr.tag in ['DEM', 'Raster', 'Vector']]

        section_out = self.section('Outputs', 'Outputs')
        outputs = list(realization.find('Outputs'))
        [self.layerprint(lyr, section_out, self.project_root) for lyr in outputs if lyr.tag in ['DEM', 'Raster', 'Vector']]


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('projectxml', help='Path to the VBET project.rs.xml', type=str)
    parser.add_argument('report_path', help='Output path where report will be generated', type=str)
    args = dotenv.parse_args_env(parser)

    cfg = ModelConfig('http://xml.riverscapes.xyz/Projects/XSD/V1/VBET.xsd', __version__)
    project = RSProject(cfg, args.projectxml)
    report = VBETReport(args.report_path, project, os.path.dirname(args.projectxml))
    report.write()
