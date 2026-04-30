import numpy as np
import os
import json
import sys
import math

import scipy

import commpy

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import modules.simulator_functions as sim




#### noise generator ####
def noise(data, num_samples_if_empty, scale=0.001):
    """
    Adds Gaussian noise to a list of complex samples ([real, imag]).
    If the input data is empty, it generates pure noise for the specified number of samples.
    """
    # If data is empty (no signal), generate pure noise for the time step
    if not data:
        real_part = np.random.normal(0, scale, num_samples_if_empty)
        imag_part = np.random.normal(0, scale, num_samples_if_empty)
        return np.stack((real_part, imag_part), axis=-1).tolist()

    # If data exists, convert to numpy, add noise, and convert back to list
    data_np = np.array(data)
    noise_np = np.random.normal(0, scale, data_np.shape)
    return (data_np + noise_np).tolist()







def nlos_element(sample, fc, tx_location, element_location, rx_location, normal, bn, ris_length, ris_width,counter,tau):

    # print("element working \n")
     
    pt=1
    gt=1
    q=0.285
    ep=1
    c=3e8

    r_in_vec = np.array(element_location) - np.array(tx_location)
    # print(r_in_vec,"\n")
    r_rn_vec = np.array(rx_location) - np.array(element_location)
    r_in = np.linalg.norm(r_in_vec)
    r_rn = np.linalg.norm(r_rn_vec)

    #print("r_in:", r_in, "r_rn:", r_rn)

    # FIX 1: Clamp the input to arccos to prevent NaN from floating point errors
    cos_phi_i_arg = np.clip(np.dot(r_in_vec, normal) / r_in, -1.0, 1.0)
    cos_phi_r_arg = np.clip(np.dot(r_rn_vec, normal) / r_rn, -1.0, 1.0)

    # print("cos_phi_i_arg:", cos_phi_i_arg, "\n")

    phi_i = np.arccos(cos_phi_i_arg)
    phi_r = np.arccos(cos_phi_r_arg)

    # print("phi_i:", phi_i, "\n")


    # Check for NaN or zero distances to prevent errors
    if r_in == 0 or r_rn == 0 or np.isnan(phi_i) or np.isnan(phi_r):
        return [0.0, 0.0]

    # FIX: If the angle of incidence or reflection is > 90 degrees,
    # the signal is blocked, so the contribution is zero.
    # This prevents taking a non-integer power of a negative number.
    cos_phi_i = np.abs(np.cos(phi_i))
    cos_phi_r = np.abs(np.cos(phi_r))

    # print(cos_phi_i, cos_phi_r, " helllooo\n")
    # if cos_phi_i < 0 or cos_phi_r < 0:
    #     return [0.0, 0.0]

    p_rn_amplitude = pt * gt * q * ep * (ris_length * ris_width) 
    p_rn_amplitude *= c 
    b =  4 * np.pi * fc
    p_rn_amplitude *=p_rn_amplitude/b**2
    p_rn_amplitude *= np.pi * (cos_phi_i**(2*q)) 
    p_rn_amplitude *= (cos_phi_r**(2*q)) 
    p_rn_amplitude *= (1/(r_in**2)) * (1/(r_rn**2))
    #print("p_rn_amplitude:", p_rn_amplitude, "\n")
    phi_n_phase = (np.exp(2j * np.pi * fc * (counter * tau - (r_in+r_rn) / c)))

    # This is the complex channel gain for the NLOS path through one element
    channel_gain = bn * np.sqrt(p_rn_amplitude) * np.exp(1j * phi_n_phase)
    #print("channel_gain:", channel_gain, "\n")

    # FIX 2: Apply the gain to the input sample and return a [real, imag] list
    input_signal = sample
    output_signal = input_signal * channel_gain

    #print([output_signal.real, output_signal.imag],"\n")
    return [output_signal.real, output_signal.imag]




def coordinate_matrix_gen(plane, location, unit_cell_m_length, unit_cell_n_length, unit_cell_gap, array_size):
    
    coordinates = []
    for m in range(array_size[0]):
        coordi_row = []
        for n in range(array_size[1]):
            if plane == 1 or plane == 4:
                x = location[0] + unit_cell_n_length/2 + unit_cell_gap + n * (unit_cell_n_length + unit_cell_gap)
                y = location[1] + unit_cell_m_length/2 + unit_cell_gap + m * (unit_cell_m_length + unit_cell_gap)
                z = location[2]
            elif plane == 2 or plane == 5:
                x = location[0]
                y = location[1] + unit_cell_n_length/2 + unit_cell_gap + n * (unit_cell_n_length + unit_cell_gap)
                z = location[2] + unit_cell_m_length/2 + unit_cell_gap + m * (unit_cell_m_length + unit_cell_gap)
            elif plane == 3 or plane == 6:
                x = location[0] + unit_cell_n_length/2 + unit_cell_gap + n * (unit_cell_n_length + unit_cell_gap)
                y = location[1] 
                z = location[2] + unit_cell_m_length/2 + unit_cell_gap + m * (unit_cell_m_length + unit_cell_gap)
            else:
                raise ValueError("Invalid plane specified.")
            coordi_row.append([x, y, z])
        coordinates.append(coordi_row)    
    return coordinates


def phase_matrix_gen(ris_config):
    """
    Generates a phase matrix based on the RIS configuration.
    The configuration is expected to be a list of lists, where each inner list contains the phase values for each element.
    """
    phase_mat = []
    for row in ris_config:
        phase_row = []
        for element_config in row:
           
            # phase_value = np.exp(np.pi/4 * 1j * element_config)
            phase_value = np.exp(np.pi/4 * 1j) * element_config
            phase_row.append(phase_value)
        phase_mat.append(phase_row)    
        
    return phase_mat
    

def get_normal(plane):
    """
    Returns the normal vector for the specified plane.
    """
    if plane == 1:
        return np.array([0, 0, -1])
    elif plane == 2:
        return np.array([-1, 0, 0])
    elif plane == 3:
        return np.array([0, -1, 0])
    elif plane == 4:
        return np.array([0, 0, 1])
    elif plane == 5:
        return np.array([1, 0, 0])
    elif plane == 6:
        return np.array([0, 1, 0])
    else:
        raise ValueError("Invalid plane specified.")   

def total_nlos_gain(fc, tx_location, rx_location):
    """
    Calculates the total complex channel gain from all RIS elements.
    This is the sum of gains from each individual element path.
    """
    total_gain = 0j
    with open("config/ris.json", "r") as f:
        ris_config = json.load(f)
    
    for ris in ris_config["ris"]:
        normal = get_normal(ris["plane"])
        ris_length = (ris["unit_cell_m_length"] + ris["unit_cell_gap"]) * ris["array_size"][0]
        ris_width = (ris["unit_cell_n_length"] + ris["unit_cell_gap"]) * ris["array_size"][1]
        ris_configuration = ris["configuration_matrix"]
        coordinate_matrix = coordinate_matrix_gen(ris["plane"], ris["location"], ris["unit_cell_m_length"], ris["unit_cell_n_length"], ris["unit_cell_gap"], ris["array_size"])
        phase_matrix = phase_matrix_gen(ris_configuration)

        for i in range(len(coordinate_matrix)):
            for j in range(len(coordinate_matrix[i])):
                element_coordinate = coordinate_matrix[i][j]
                b_n = phase_matrix[i][j]
                
                # Simplified nlos_element logic to return gain only
                pt=1; gt=1; q=0.285; ep=1; c=3e8
                r_in_vec = np.array(element_coordinate) - np.array(tx_location)
                r_rn_vec = np.array(rx_location) - np.array(element_coordinate)
                r_in = np.linalg.norm(r_in_vec)
                r_rn = np.linalg.norm(r_rn_vec)

                if r_in == 0 or r_rn == 0: continue

                cos_phi_i_arg = np.clip(np.dot(r_in_vec, normal) / r_in, -1.0, 1.0)
                cos_phi_r_arg = np.clip(np.dot(r_rn_vec, normal) / r_rn, -1.0, 1.0)
                phi_i = np.arccos(cos_phi_i_arg)
                phi_r = np.arccos(cos_phi_r_arg)
                cos_phi_i = np.abs(np.cos(phi_i))
                cos_phi_r = np.abs(np.cos(phi_r))

                p_rn_amplitude = pt * gt * q * ep * (ris_length * ris_width) * c
                b = 4 * np.pi * fc
                p_rn_amplitude = (p_rn_amplitude**2) / (b**2)
                p_rn_amplitude *= np.pi * (cos_phi_i**(2*q)) * (cos_phi_r**(2*q))
                p_rn_amplitude *= (1/(r_in**2)) * (1/(r_rn**2))
                
                # Correct phase calculation
                phase_angle = -2 * np.pi * fc * (r_in + r_rn) / c
                element_gain = b_n * np.sqrt(p_rn_amplitude) * np.exp(1j * phase_angle)
                total_gain += element_gain

    return total_gain
                

 
#### function to generate LOS signal value for each tau samples #####
def signal(complex_data, tx_location, rx_location, fc,counter,tau):

    c = 3e8  # Speed of light

    # Convert locations to numpy arrays and calculate distance
    tx_pos = np.array(tx_location)
    rx_pos = np.array(rx_location)
    distance = np.linalg.norm(rx_pos - tx_pos)

    if distance == 0:
        distance = 1e-6 # Avoid division by zero if locations are identical

    Fs=int(6e4)
    Ts=tau / len(complex_data)
    ups=int(Ts * Fs)
    N=len(complex_data)


    t0 = 3*Ts  


    # Calculate the filter coefficients (N=number of samples in filter)
    _, rrc = commpy.filters.rrcosfilter(N=int(2*t0*Fs), alpha=1,Ts=Ts, Fs=Fs)
    t_rrc = np.arange(len(rrc)) / Fs  # the time points that correspond to the filter values

    dk=np.array(complex_data)
    # t_symbols = Ts * np.arange(N)

    x = np.zeros(ups*N, dtype='complex')
    x[::ups] = dk  # every ups samples, the value of dn is inserted into the sequence
    # t_x = np.arange(len(x))/Fs
    u = np.convolve(x, rrc)

    # --- LOS Path Calculation ---
    t_los = (counter*tau + np.arange(len(u))/Fs) + distance/c
    i_los = u.real
    q_los = u.imag
    iup_los = i_los * np.cos(2*np.pi*t_los*fc)  
    qup_los = -q_los * np.sin(2*np.pi*t_los*fc)
    s_los = iup_los + qup_los

    # --- NLOS (RIS) Path Calculation ---
    # 1. Calculate the total complex gain from all RIS elements
    nlos_gain = total_nlos_gain(fc, tx_location, rx_location)

    # 2. Apply this gain to the baseband signal
    u_nlos = u * nlos_gain

    # 3. Upconvert the NLOS signal to passband
    # Note: The time vector for NLOS would be different for each element.
    # We use the LOS time as an approximation for simplicity here.
    t_nlos = t_los 
    i_nlos = u_nlos.real
    q_nlos = u_nlos.imag
    iup_nlos = i_nlos * np.cos(2*np.pi*t_nlos*fc)
    qup_nlos = -q_nlos * np.sin(2*np.pi*t_nlos*fc)
    s_nlos = iup_nlos + qup_nlos

    # --- Combine LOS and NLOS signals at the receiver ---
    s = s_nlos + s_los
    # s = s_los

    del_f = 0
    # Apply path loss to the combined signal during down-conversion
    idown = (s * np.cos(2*np.pi*(fc-(del_f))*(t_los)))/distance
    qdown = (-s * np.sin(2*np.pi*(fc-(del_f))*(t_los)))/distance

    BN = 1/(2*Ts )

    cutoff = 5*BN        # arbitrary design parameters
    lowpass_order = 51   
    lowpass_delay = (lowpass_order // 2)/Fs  # a lowpass of order N delays the signal by N/2 samples (see plot)
    # design the filter
    lowpass = scipy.signal.firwin(lowpass_order, cutoff/(Fs/2))


    idown_lp = scipy.signal.lfilter(lowpass, 1, idown)
    qdown_lp = scipy.signal.lfilter(lowpass, 1, qdown)

    v = 10*(idown_lp + 1j*qdown_lp)

    

    y = np.convolve(v, rrc) / (sum(rrc**2)) * 2

    delay = int((2*t0 + lowpass_delay)*Fs)

    t_y = np.arange(len(y))/Fs
    t_samples = t_y[delay::ups]
    y_samples = y[delay::ups]  

    y_output=y_samples[:N]

    formatted_output = [[val.real, val.imag] for val in y_output]

    return formatted_output


           
def process_samples(data, tx_location, rx_location, fc,counter,tau):
    

    #print(data)
    complex_data=[complex(sample[0], sample[1]) for sample in data]  # Convert to complex numbers
    
    
    # totalnlos = np.array([0.0, 0.0], dtype=np.float64)  # Initialize total NLOS signal
    # for sample in data:
    #     nlos_signal = np.array(total_nlos(sample, fc, tx_location, rx_location,counter,tau))
    #     totalnlos += nlos_signal

        #print(sample)
        
        # Calculate LOS signal for the current sample
    full_signal = np.array(signal(complex_data, tx_location, rx_location, fc, counter, tau))

        # Calculate total NLOS signal (from all RIS) for the current sample
        # nlos_signal = np.array(total_nlos(sample, fc, tx_location, rx_location,counter,tau))

        #print("los_signal:", los_signal, "\n")
        #print("nlos_signal:", nlos_signal, "\n")

        # Add LOS and NLOS signals together (superposition)
    total_signal = (full_signal).tolist()
        #total_signal=los_signal
    # processed_data.append(total_signal)

    return total_signal