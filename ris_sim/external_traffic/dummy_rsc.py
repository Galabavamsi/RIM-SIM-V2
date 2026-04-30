import random

def dumrsc(data, array_size):
    """
    Dummy resource configuration function that simulates the generation of a configuration matrix.
    
    Args:
        data (dict): The data containing RIS configurations.
        array_size (int): The size of the RIS array.
    
    Returns:
        list: A dummy configuration matrix.
    """
    configuration_matrix = []
    for i in range(array_size[0]):
        row = []
        for j in range(array_size[1]):
            # Generate a dummy phase value for each element
            # element_config = random.choice([0, 1])
            element_config = 1
            row.append(element_config)
        configuration_matrix.append(row)

    return configuration_matrix    