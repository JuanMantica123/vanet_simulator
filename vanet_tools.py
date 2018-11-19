import pandas as pd
import matplotlib.pyplot as plt
import logging 
from scipy.spatial import distance
from collections import defaultdict
from math import isnan
import math
from multiprocessing.dummy import Pool as ThreadPool 
import numpy as np
import os.path

XCOLUMN_NAME = 'X'
YCOLUMN_NAME = 'Y'

def create_coords(coordinates,microcloud_range,num_microclouds=5):
    microclouds_coords =  []
    while(len(microclouds_coords)<num_microclouds):
        random_coord = coordinates.sample().get_values()[0]
        overlaps = False
        for coord in microclouds_coords:
            if distance.euclidean(coord, random_coord)<microcloud_range: 
                overlaps = True
                break
        if not overlaps:
            microclouds_coords.append(random_coord)
    return microclouds_coords

def plot_microclouds(microcloud_coords,microcloud_range,coords_x,coords_y):
    fig, ax = plt.subplots()
    plt.scatter(coords_x,coords_y,c='red')
    plt.xlabel("x coordinate")
    plt.ylabel("y coordinate")
    plt.title("microclouds")
    for microcloud_coord in microcloud_coords:
        microcloud = plt.Circle(microcloud_coord,microcloud_range)
        ax.add_artist(microcloud)
    plt.show()

def store_microcloud_config(coordinates,coords_config_name,num_clouds,microcloud_range):
    if not os.path.isfile(coords_config_name):
        microclouds_coords = create_coords(coordinates,microcloud_range,num_microclouds=num_clouds)
        coords_df = pd.DataFrame(microclouds_coords,columns=[XCOLUMN_NAME,YCOLUMN_NAME])
        coords_df.to_csv(coords_config_name)

def parse_configuration(coords_config_name):
    if os.path.isfile(coords_config_name):
        coords_df = pd.read_csv(coords_config_name)
        micro_clouds = []
        for i,row in coords_df.iterrows():
            micro_clouds.append((row[XCOLUMN_NAME],row[YCOLUMN_NAME]))
        return micro_clouds
    else:
        raise FileNotFoundError("No file named {} was found".format(coords_config_name))
        
def plot_results(results_df):
    for column in results_df:
        if column!='num_clouds' and column!='average_latency':
            plt.xlabel('num_clouds')
            plt.ylabel(column)
            plt.plot(results_df['num_clouds'],results_df[column])
            plt.show()
    plt.xlabel('num_clouds')
    plt.ylabel('average_latency')
    df_without_nan = results_df.dropna()
    plt.xlim(left=0,right = max(df_without_nan['average_latency']))
    plt.plot(df_without_nan['num_clouds'],df_without_nan['average_latency'])


class Block:
    def __init__(self,identifier,size):
        self.identifier = identifier
        self.size = size
    def __eq__(self, other):
        return other and self.identifier == other.identifier

class Microcloud:
    def __init__(self,id_,x,y,ant_range,blocks,bandwith):
        self.id = id_
        self.x,self.y = x,y
        self.ant_range = ant_range
        self.blocks = blocks
        self.bandwith = bandwith
        
    def in_range(self,other_x,other_y):
        return distance.euclidean((self.x,self.y), (other_x,other_y))<=self.ant_range
    
    def has_block(self, block):
        return block in self.blocks
    
    def get_data(self):
        return self.bandwith
class Node:
    def __init__(self,df,blocks):
        self.id = df.iloc[0]['vehicle_id'] #Note that the id of the node is taken from the df generated by sumo
        self.df = df
        self.blocks = blocks[:]
        self.blocks_progress = [0 for n in range(len(blocks))]
        self.blocks_downloading = [False for n in range(len(blocks))]
        #Note the one to one relationship between block and microcloud
        self.microcloud_to_block = defaultdict(lambda:-1)
        self.blocks_downloaded = 0
        self.init_time = df.iloc[0]['timestep_time']
        self.latency = -1
    
    def find_block(self,microcloud):
        for index,block in enumerate(self.blocks):
            block_progress = self.blocks_progress[index]
            downloading = self.blocks_downloading[index]
            if microcloud.has_block(block) and block_progress<block.size and not downloading: #i.e the block has not been downloaded
                return index
        return -1
    
    def download_block(self,x,y,microcloud,time):
        if not microcloud.in_range(x,y):
            block_index = self.microcloud_to_block[microcloud]
            if block_index!=-1:
                block,progress = self.blocks[block_index],self.blocks_progress[block_index]
                debug= "Stopping download for block {} on car {} with microcloud {}, last progress : {}".format(block.identifier,self.id,microcloud.id,progress)
                logging. debug(debug)
                self.microcloud_to_block[microcloud], self.blocks_progress[block_index],self.blocks_downloading[block_index] = -1,0,False
        elif self.microcloud_to_block[microcloud]==-1:
            block_index = self.find_block(microcloud)
            if block_index!=-1:
                block = self.blocks[block_index]
                debug= "Initiated download for block {} on car {} with microcloud {}".format(block.identifier,self.id,microcloud.id)
                logging.debug(debug)
                self.microcloud_to_block[microcloud],self.blocks_downloading[block_index] = block_index,True
        else:
            block_index = self.microcloud_to_block[microcloud]
            self.blocks_progress[block_index]+=microcloud.get_data()
            block,progress = self.blocks[block_index],self.blocks_progress[block_index]
            debug= "Continuing download for block {} on car {} with microcloud {} latest progress: {}".format(block.identifier,self.id,microcloud.id,progress)
            logging.debug(debug)
            if progress>=block.size:
                debug= "Download finished for block {} on car {} with microcloud {}".format(block.identifier,self.id,microcloud.id)
                logging.debug(debug)
                self.microcloud_to_block[microcloud] = -1
                self.blocks_downloading[block_index]= False      
                self.blocks_downloaded+=1
                if(self.blocks_downloaded==len(self.blocks)):
                    self.latency=time-self.init_time

    
    def simulate(self,microclouds):
        logging.debug("Id {}".format(self.id))
        for index, row in self.df.iterrows():
            x,y,time = row['vehicle_x'],row['vehicle_y'],row['timestep_time']
            logging.debug("Time {}".format(time))
            for microcloud in microclouds:
                self.download_block(x,y,microcloud,time)
        return [self.id, self.blocks_downloaded,self.latency]
    
class Simulator:
    def __init__(self,df):
        self.car_groups = df.sort_values(by='timestep_time').groupby('vehicle_id')
        self.cars = df['vehicle_id'].unique()

    
    def simulation(self,microclouds_coords,microcloud_range,blocks_per_microcloud= 3,bandwith = 1,block_size = 5,total_blocks =12):
        blocks = [Block(i,block_size) for i in range(total_blocks)]
        microclouds = []
        block_index = 0
        for i,coord in enumerate(microclouds_coords):
            microcloud_blocks = []
            for b in range(blocks_per_microcloud):
                block = blocks[block_index]
                block_index+=1
                block_index%=len(blocks)
                microcloud_blocks.append(block)
            microcloud = Microcloud(i,coord[0],coord[1],microcloud_range,microcloud_blocks,bandwith)
            microclouds.append(microcloud)
        nodes = []
        for car in self.cars:
            car_df = self.car_groups.get_group(car)
            node = Node(car_df,blocks)
            nodes.append(node)
        logging.info("Finished setup started simulation with {} microclouds".format(len(microclouds_coords)))
        pool = ThreadPool(8) 
        results = pool.map(lambda node:node.simulate(microclouds), nodes)
        return results

    def simulation_by_number_of_clouds(self,micro_clouds,microcloud_range,step=1,bandwith=1,total_blocks=12):
        logging.getLogger().setLevel(logging.INFO)
        stats = []
        for cloud_index in range(1,len(micro_clouds)+1,step):
            microclouds_coords = micro_clouds[:cloud_index]
            num_clouds = len(microclouds_coords)
            logging.info("Starting simulation with {} num of clouds".format(cloud_index))
            results = self.simulation(microclouds_coords,microcloud_range,bandwith=bandwith,total_blocks=total_blocks)
            stats_df = pd.DataFrame(results,columns=['id','blocks_received','latency'])
            blocks_received = stats_df['blocks_received']
            block_percentage = blocks_received.mean()/total_blocks  
            ninety_five_percentily = np.percentile(blocks_received,5)
            files_downloaded = len(stats_df[stats_df['blocks_received']==total_blocks])
            average_latency = stats_df[stats_df['latency']>0]['latency'].mean()
            stats.append([num_clouds,block_percentage,ninety_five_percentily,files_downloaded,average_latency])
        return stats

