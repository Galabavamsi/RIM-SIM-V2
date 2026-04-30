import os
import sys
import time
import json
import math
import numpy as np
import time


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import modules.simulator_functions as sim
import modules.mobility_functions as mobility
import modules.channel_functions as channel
import external_traffic.dummy_rsc as rsc



### loading room dimensions ###
with open('config/room.json') as f:
        room_data = json.load(f)
        room_length = room_data['room']['length']
        room_width = room_data['room']['width']
        room_height = room_data['room']['height']

tau=0.002  #seconds

### main event loop ####

counter=0

start_time = time.time()
while True:




    # giving required previous parameters to rsc to calculate configuration #
    # and update ris configuration in ris json for present/next tau #


    #### implementing a static dummy rsc for now ####
    
    with open('config/ris.json', 'r+') as f:
        # 1. Read the current RIS configuration
        ris_config_data = json.load(f)
        
        # 2. Load the output from the previous time step
        try:
            with open('config/output.json', 'r') as output_file:
                previous_output_data = json.load(output_file)
        except (FileNotFoundError, json.JSONDecodeError):
            # If the file doesn't exist or is empty, provide a default structure
            previous_output_data = {"outputs": []}
            
        # 3. Call the RSC function with the previous output as input
        # Assuming rsc.dumrsc needs the previous output and the RIS array size
        # Note: You may need to adjust parameters based on your rsc.dumrsc implementation
        new_configuration = rsc.dumrsc(previous_output_data, ris_config_data['ris'][0]['array_size'])

        # 4. Update the configuration in the RIS data structure
        ris_config_data['ris'][0]['configuration_matrix']=new_configuration
        # ris_config_data['ris'][1]['configuration_matrix'] =new_configuration


        # 5. Write the new configuration back to the ris.json file
        f.seek(0)  # Move the cursor to the beginning of the file
        json.dump(ris_config_data, f, indent=4)  # Write the updated data
        f.truncate()  # Remove any leftover data from previous writes
    



    ##### doing the nodes mobility for each tau ######

    with open('config/nodes.json', 'r+') as f:
        # 1. Read the data
        data = json.load(f)
        nodes = data['nodes']

        for node in nodes:
            new_location=mobility.do_mobility(node,room_length,room_width,tau)
            
            node['location']=new_location

        f.seek(0) 
        json.dump(data, f, indent=4) 
        f.truncate() 


    #### assigning node nature according to request queue ####

    with open('config/nodes.json', 'r+') as f:
        # 1. Read the data
        data = json.load(f)
        nodes = data['nodes']


        for node in nodes:
            if node['current_mode'] == 'idle':


               
                    
                if node['request']:
                    if node['request']['mode'] == 'transmit':

                        node['current_mode']= 'transmit'
                        node['fc']= node['request']['fc']
                        node['sample_rate']= node['request']['sample_rate']
                        node['data']= node['request']['data']
                        node['req_time']=int(len(node['data'][0])/(node['sample_rate'] * tau))

                        node['next_update']=counter+int(node['req_time'])+1
                        node['current_counter']=counter
                        node['request']={}
                    


                    elif node['request']['mode'] == 'receive':
                        
                        node['current_mode']= 'receive'
                        node['fc']= node['request']['fc']
                        node['sample_rate']= node['request']['sample_rate']
                        node['req_time'] = int((node['request']['num_samps'])/(node['sample_rate'] * tau))

                        node['next_update']=counter+int(node['req_time'])+1
                        node['current_counter']=counter
                        node['request']={}
                        with open('config/output.json', 'r+') as output_file:
                            output_data = {
                                'id': node['id'],
                                'fc': node['fc'],
                                'sample_rate': node['sample_rate'],
                                'data': []
                            }
                            # FIX: Check if the file is empty before trying to load it
                            try:
                                output_file_data = json.load(output_file)
                            except json.JSONDecodeError:
                                # If file is empty or invalid, create the base structure
                                output_file_data = {"outputs": []}

                            output_file_data['outputs'].append(output_data)
                            output_file.seek(0)
                            json.dump(output_file_data, output_file, indent=4)
                            output_file.truncate()

        f.seek(0) 
        json.dump(data, f, indent=4) 
        f.truncate() 
            







    #### creating temporary data for nodes in transmit mode ####
    

    with open('config/nodes.json', 'r+') as f:
        data = json.load(f)
        nodes = data['nodes']
        
        temp_data={}  ## dictionary to hold temp data for nodes in transmit mode for one tau
        for node in nodes:
            if node['current_mode']=="transmit":
                tau_samp= int(node['sample_rate'] * tau)
                if len(node['data'][0]) >= tau_samp:  ## if data is enough for one tau
                    temp_data[node['id']]= node['data'][0][:tau_samp]
                    node['data'][0] = node['data'][0][tau_samp:]

                else:  ## if data is not enough for one tau
                    padding_count = tau_samp - len(node['data'][0]) ### padding the data to make it equal to tau_samp
                    padding=[]
                    for i in range(padding_count):
                        padding.append(0)
                    temp_data[node['id']]= node['data'][0]
                    temp_data[node['id']].extend(padding)
                    node['data'][0] = []
                        


        f.seek(0)  
        json.dump(data, f, indent=4) 
        f.truncate() 
            
            
    
    ##### configurations from rsc ######
                    



    #### processing nodes according to their nature ####
                                    
    with open('config/nodes.json', 'r+') as f:  ##opening the nodes json
        data = json.load(f)
        nodes = data['nodes'] ## loading nodes data (dictionary)
        all_used_ids=[]  ## collecting the tx ids that are used in this iteration , to change state of nodes after processing
        for node in nodes:
            if node['current_mode'] == 'receive':
                ID = sim.check_available_tx(node['fc'])
                
                # Calculate the number of samples this receiver expects in one time step (tau).
                tau_samp = int(node['sample_rate'] * tau)
                output_data=[]

                for id in ID:
                    if id not in all_used_ids:
                        all_used_ids.append(id)
                    
                    # Get the original data for this time step
                    original_tx_data = temp_data[id]

                    
                    
                    tx_location = sim.get_location(id)
                    process_data = channel.process_samples(original_tx_data,
                                                        tx_location,
                                                        node['location'],
                                                        node['fc'],
                                                        counter,tau)
                    output_data = sim.add(output_data,process_data)
                       
                # FIX: Pass the expected number of samples to the noise function.
                #output_data=channel.noise(output_data, tau_samp)   

                with open('config/output.json', 'r+') as output_file:
                        # FIX: Check if the file is empty before trying to load it
                        try:
                            output_file_data = json.load(output_file)
                        except json.JSONDecodeError:
                            # This case should be rare here, but it's safe to handle
                            output_file_data = {"outputs": []}
                                               
                        for entry in output_file_data['outputs']:
                            if entry['id'] == node['id'] and entry['fc'] == node['fc']:
                                entry['data'].append(output_data)
                                break 
                        output_file.seek(0)
                        json.dump(output_file_data, output_file, indent=4)
                        output_file.truncate()  
                
                node['req_time'] -= 1
                node['current_counter'] += 1

                if node['req_time'] == 0:
                    node['current_mode'] = 'idle'
                    node['next_update'] = -1
                    node['current_counter'] = -1
                    node['fc'] = -1
                    node['sample_rate'] = -1
                    node['data'] = []

                
                        
        for id in all_used_ids:
            for node in nodes:
                if node['id'] == id:
                    node['req_time'] -= 1
                    node['current_counter'] += 1
                    if node['req_time'] == 0:
                        node['current_mode'] = 'idle'
                        node['next_update'] = -1
                        node['current_counter'] = -1
                        node['fc'] = -1
                        node['sample_rate'] = -1
                        node['data'] = []
                                                                  

        f.seek(0)  
        json.dump(data, f, indent=4) 
        f.truncate() 

    


    with open('config/nodes.json', 'r+') as f:
        data = json.load(f)
        nodes = data['nodes']
        all_idle = all(node['current_mode'] == 'idle' for node in nodes)
        if all_idle:
            break
                                    
    counter += 1  #incrementing the global counter



end_time = time.time()
elapsed_time = end_time - start_time
print(f"Total time taken for simulation: {elapsed_time} seconds")