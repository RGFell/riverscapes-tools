""" Delete Projects

This script is used to delete projects from the Riverscapes server. It is a dangerous script and should be used with caution. 

Args:
    environment (str): The stage to run the script on
    working_folder (str): The top level folder for downloads and output
    csv_file (str): The CSV file with project ids to delete

Returns:
    int: 0 if successful
"""

import os
import sys
import argparse
from datetime import datetime

from rscommons import dotenv, Logger

from cybercastor.classes.RiverscapesAPI import RiverscapesAPI


def delete_projects(riverscapes_api: RiverscapesAPI, project_ids: list):
    """Delete projects from the server

    Args:
        riverscapes_api (RiverscapesAPI): The Riverscapes API object
        project_ids (list): A list of project ids to delete

    Returns:
        list: list of project ids that were deleted
    """
    log = Logger('Delete Project')

    # TODO - Add a query to check if the project exists before deleting it
    # query_script = riverscapes_api.load_query('searchProject')

    mutation_script = riverscapes_api.load_mutation('deleteProject')

    deleted_projects = []
    for project in project_ids:
        result = riverscapes_api.run_query(mutation_script, {"projectId": project, 'options': {'totalDelete': True}})
        if result is not None:
            if result['data']['deleteProject']['success']:
                deleted_projects.append(project)
                log.info(f'Project {project} deleted')
        else:
            log.error(f'Project {project} not deleted')

    return deleted_projects


def main():
    """
    Delete Projects
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('environment', help='Riverscapes stage', type=str, default='production')
    parser.add_argument('working_folder', help='top level folder for downloads and output', type=str)
    parser.add_argument('csv_file', help='CSV file with project ids to delete', type=str)

    args = dotenv.parse_args_env(parser)

    if not os.path.exists(args.working_folder):
        os.makedirs(args.working_folder)

    log = Logger('Delete Projects')
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    log.setup(logPath=os.path.join(args.working_folder, f'delete_projects_{timestamp}.log'))

    riverscapes_api = RiverscapesAPI(stage=args.environment)
    if riverscapes_api.accessToken is None:
        riverscapes_api.refresh_token()

    project_ids = []
    with open(args.csv_file, 'r', encoding='utf-8') as f:
        for line in f:
            project_ids.append(line.strip())

    deleted_projects = delete_projects(riverscapes_api, project_ids)

    # create a csv file with the deleted projects
    with open(os.path.join(args.working_folder, f'deleted_projects_{timestamp}.csv'), 'w', encoding='utf-8') as f:
        for project in deleted_projects:
            f.write(f'{project}\n')

    log.info('Process complete')

    riverscapes_api.shutdown()

    log.info('Shutting down api connection')

    sys.exit(0)


if __name__ == '__main__':
    main()
