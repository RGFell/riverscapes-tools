"""
Author:         Rodrigo Gomez Fell

Date:           18 Nov 2024

Description:    This script processes the feature layer riverline in the New Zealand RECv2 dataset and gives each riverline segment a unique network ID based on its node connections.  

                
"""


import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
import networkx as nx


def main():
    path = input("Enter the path: ")
    filename = input("Enter the filename: ")
    feature_class = input("Enter the feature class: ")

    # Load the data from the GeoPackage
    gdf = gpd.read_file(f"{path}/{filename}", layer=feature_class)

    # Add a new column to store the unique network ID
    new_field = "NetworkID"
    if new_field not in gdf.columns:
        gdf[new_field] = None

    # Create dictionaries to store the connections
    from_to_dict = {}
    to_from_dict = {}

    # Read the FROM_NODE and TO_NODE into the dictionaries
    for idx, row in gdf.iterrows():
        from_node = row['FROM_NODE']
        to_node = row['TO_NODE']
        objectid = row['OBJECTID']

        if from_node not in from_to_dict:
            from_to_dict[from_node] = []
        from_to_dict[from_node].append((to_node, objectid))

        if to_node not in to_from_dict:
            to_from_dict[to_node] = []
        to_from_dict[to_node].append((from_node, objectid))

    # Function to traverse the network using a graph
    def traverse_network(start_node, visited_nodes, network_id):
        stack = [start_node]

        while stack:
            node = stack.pop()

            if node not in visited_nodes:
                visited_nodes[node] = network_id

                # Traverse the from_node connections
                if node in from_to_dict:
                    for to_node, _ in from_to_dict[node]:
                        stack.append(to_node)

                # Traverse the to_node connections
                if node in to_from_dict:
                    for from_node, _ in to_from_dict[node]:
                        stack.append(from_node)

    # Assign unique network IDs
    network_id = 0
    visited_nodes = {}

    # Start traversing the network and assign Network IDs
    for idx, row in gdf.iterrows():
        from_node, to_node = row['FROM_NODE'], row['TO_NODE']

        if from_node not in visited_nodes and to_node not in visited_nodes:
            network_id += 1
            traverse_network(from_node, visited_nodes, network_id)

        gdf.at[idx, new_field] = visited_nodes[from_node]

    # Save the updated GeoDataFrame back to the GeoPackage
    gdf.to_file(f'{path}/{filename}', layer=feature_class, driver="GPKG")

    print("Network ID assignment complete.")


if __name__ == "__main__":
    main()
