import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import modules.simulator_functions as sim


center_freq= 2.4e9-1800-800-450
sampling=5880.0

sim.recieve_from_simulator(2389,center_freq,sampling,'node_2')