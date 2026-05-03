import numpy as np
import os
import sys
import math

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import modules.json_store as store




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


def _unit_vector(vec):
    norm = np.linalg.norm(vec)
    if norm == 0 or not np.isfinite(norm):
        return None, norm
    return vec / norm, norm


def element_visibility(tx_location, element_location, rx_location, normal):
    """
    Returns the RIS angular visibility term for front-side illumination.

    The previous implementation used abs(cos(theta)) to avoid fractional powers of
    negative cosines. That prevents NaNs, but it also turns a physically back-side
    path into a front-side contribution. This function keeps the mathematical
    safety while preserving the surface orientation: negative cosines are blocked.
    """
    element = np.array(element_location, dtype=float)
    normal_vec, normal_norm = _unit_vector(np.array(normal, dtype=float))
    if normal_vec is None:
        return 0.0

    to_tx, r_in = _unit_vector(np.array(tx_location, dtype=float) - element)
    to_rx, r_out = _unit_vector(np.array(rx_location, dtype=float) - element)
    if to_tx is None or to_rx is None or r_in == 0 or r_out == 0:
        return 0.0

    cos_i = float(np.dot(to_tx, normal_vec))
    cos_r = float(np.dot(to_rx, normal_vec))
    if cos_i <= 0.0 or cos_r <= 0.0:
        return 0.0
    return math.sqrt(cos_i * cos_r)


def reflection_coefficient(ris, state):
    """
    Convert an RIS configuration state into a complex reflection coefficient.

    Preferred config format:
        "phase_response": {"1": [real, imag]}

    Numeric states without a lookup are treated as direct real-valued coefficients
    for backward compatibility with the existing dummy controller.
    """
    response = ris.get("phase_response", {}) if isinstance(ris, dict) else {}
    key = str(state)
    if key in response:
        value = response[key]
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return complex(float(value[0]), float(value[1]))
        return complex(value)
    return complex(state)


def free_space_coefficient(fc, distance):
    """Baseband free-space field coefficient for a single path."""
    if fc <= 0 or not math.isfinite(float(fc)):
        raise ValueError("fc must be a positive finite frequency.")
    if distance <= 0 or not math.isfinite(float(distance)):
        return 0j
    c = 3e8
    wavelength = c / float(fc)
    amplitude = wavelength / (4.0 * math.pi * distance)
    phase = -2.0 * math.pi * distance / wavelength
    return amplitude * np.exp(1j * phase)







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
    ris_config = store.load_json("config/ris.json", default={"ris": []})

    for ris in ris_config["ris"]:
        normal = get_normal(ris["plane"])
        ris_configuration = ris["configuration_matrix"]
        coordinate_matrix = coordinate_matrix_gen(ris["plane"], ris["location"], ris["unit_cell_m_length"], ris["unit_cell_n_length"], ris["unit_cell_gap"], ris["array_size"])

        for i in range(len(coordinate_matrix)):
            for j in range(len(coordinate_matrix[i])):
                element_coordinate = coordinate_matrix[i][j]
                b_n = reflection_coefficient(ris, ris_configuration[i][j])
                
                element = np.array(element_coordinate, dtype=float)
                tx = np.array(tx_location, dtype=float)
                rx = np.array(rx_location, dtype=float)
                r_in = np.linalg.norm(element - tx)
                r_rn = np.linalg.norm(rx - element)
                visibility = element_visibility(tx_location, element_coordinate, rx_location, normal)
                if visibility == 0.0:
                    continue

                # Cascaded baseband field coefficient: Tx->element and element->Rx.
                # The visibility term handles front-side incidence/reflection without
                # ever raising negative cosines to fractional powers.
                element_gain = (
                    b_n
                    * visibility
                    * free_space_coefficient(fc, r_in)
                    * free_space_coefficient(fc, r_rn)
                )
                total_gain += element_gain

    return total_gain
                

 
#### function to generate LOS signal value for each tau samples #####
def signal(complex_data, tx_location, rx_location, fc, counter, tau, sample_rate):

    if not complex_data:
        return []
    if sample_rate <= 0 or not math.isfinite(float(sample_rate)):
        raise ValueError("sample_rate must be a positive finite number.")

    tx_pos = np.array(tx_location)
    rx_pos = np.array(rx_location)
    distance = np.linalg.norm(rx_pos - tx_pos)

    h_los = free_space_coefficient(fc, distance)
    nlos_gain = total_nlos_gain(fc, tx_location, rx_location)
    total_channel = h_los + nlos_gain
    y_output = np.array(complex_data, dtype=complex) * total_channel

    formatted_output = [[val.real, val.imag] for val in y_output]

    return formatted_output


           
def process_samples(data, tx_location, rx_location, fc, counter, tau, sample_rate):
    

    #print(data)
    complex_data=[complex(sample[0], sample[1]) for sample in data]  # Convert to complex numbers
    
    
    # totalnlos = np.array([0.0, 0.0], dtype=np.float64)  # Initialize total NLOS signal
    # for sample in data:
    #     nlos_signal = np.array(total_nlos(sample, fc, tx_location, rx_location,counter,tau))
    #     totalnlos += nlos_signal

        #print(sample)
        
        # Calculate LOS signal for the current sample
    full_signal = np.array(signal(complex_data, tx_location, rx_location, fc, counter, tau, sample_rate))

        # Calculate total NLOS signal (from all RIS) for the current sample
        # nlos_signal = np.array(total_nlos(sample, fc, tx_location, rx_location,counter,tau))

        #print("los_signal:", los_signal, "\n")
        #print("nlos_signal:", nlos_signal, "\n")

        # Add LOS and NLOS signals together (superposition)
    total_signal = (full_signal).tolist()
        #total_signal=los_signal
    # processed_data.append(total_signal)

    return total_signal
