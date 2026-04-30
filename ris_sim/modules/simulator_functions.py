import json
import numpy as np
import os






#### function to send transmiter request to simulator for a node ####
def send_to_simulator(data, fc, sampling_rate, node_id):
    with open('config/nodes.json', 'r+') as file:
        config_data = json.load(file)

        for node in config_data['nodes']:
            if node['id'] == node_id:
                data_list = data
                if isinstance(data, np.ndarray):
                    if np.iscomplexobj(data):
                        data_list = np.stack((data.real, data.imag), axis=-1).tolist()
                    else:
                        data_list = data.tolist()

                node['request'] = {
                    'mode': 'transmit',
                    'fc': fc,
                    'sample_rate': sampling_rate,
                    'data': data_list
                }
                break

        file.seek(0)
        json.dump(config_data, file, indent=4)
        file.truncate()








#### function to send receiver request to simulator for a node ####
def recieve_from_simulator(num_samps,fc,sampling_rate,node_id):
    with open('config/nodes.json', 'r+') as file:
        config_data = json.load(file)
        for node in config_data['nodes']:
            if node['id'] == node_id:
                node['request'] = {
                    'mode': 'receive',
                    'fc': fc,
                    'sample_rate': sampling_rate,
                    'num_samps': num_samps
                }
                break

        file.seek(0)
        json.dump(config_data, file, indent=4)
        file.truncate()
    







def check_available_tx(fc):
    with open('config/nodes.json', 'r') as file:
        config_data = json.load(file)
        available_ids = []
        for node in config_data['nodes']:
            if node['current_mode'] == 'transmit' and node['fc'] == fc:
                available_ids.append(node['id'])
        return available_ids






#### function to add two list ######
def add(list1, list2):
    """Correctly adds two lists of [real, imag] pairs."""
    if not list1:
        return list2
    if not list2:
        return list1
    
    # Ensure lists are of the same length by padding the shorter one
    len1, len2 = len(list1), len(list2)
    if len1 > len2:
        list2.extend([[0, 0]] * (len1 - len2))
    elif len2 > len1:
        list1.extend([[0, 0]] * (len2 - len1))
    
    # Perform element-wise addition of the real and imaginary parts
    return [[a[0] + b[0], a[1] + b[1]] for a, b in zip(list1, list2)]


def add_signal(list1,list2):
    """Adds two lists of complex numbers."""
    if not list1:
        return list2
    if not list2:
        return list1
    
    # Ensure lists are of the same length by padding the shorter one
    len1, len2 = len(list1), len(list2)
    if len1 > len2:
        list2.extend([0j] * (len1 - len2))
    elif len2 > len1:
        list1.extend([0j] * (len2 - len1))
    
    # Perform element-wise addition
    return [a + b for a, b in zip(list1, list2)]

def get_location(id):
    """Retrieves the location of a node by its ID."""
    with open('config/nodes.json', 'r') as file:
        config_data = json.load(file)
        for node in config_data['nodes']:
            if node['id'] == id:
                return node['location']
    # If no matching entry is found, return a default location
    return [0, 0, 0]


def interpolate_data(samples, num_to_insert):
    """
    Upsamples signal data by inserting the average of adjacent samples.

    Args:
        samples (list): A list of samples, where each sample is [real, imag].
        num_to_insert (int): The number of new samples to insert between each original pair.

    Returns:
        list: The new list of upsampled data.
    """
    if not samples or len(samples) < 2:
        return samples  # Cannot interpolate with less than 2 samples

    interpolated_list = []
    for i in range(len(samples) - 1):
        s1 = samples[i]
        s2 = samples[i+1]

        # Add the first original sample
        interpolated_list.append(s1)

        # Calculate the average of the two adjacent samples
        avg_sample = [(s1[0] + s2[0]) / 2.0, (s1[1] + s2[1]) / 2.0]

        # Add the new averaged samples
        for _ in range(num_to_insert):
            interpolated_list.append(avg_sample)

    # Add the very last original sample
    interpolated_list.append(samples[-1])
    
    return interpolated_list


