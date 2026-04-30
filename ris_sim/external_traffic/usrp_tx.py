import time
import numpy as np
import wave
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import modules.simulator_functions as sim


# with wave.open(r"/home/mansi/Downloads/Doraemon-[AudioTrimmer.com].wav", 'rb') as wav_file:
#  frames = wav_file.readframes(wav_file.getnframes())  # Raw bytes
# samples = np.frombuffer(frames, dtype=np.int16)
# samples = samples.reshape(-1, 2)  # Assuming stereo
# samples = samples.mean(axis=1).astype(np.int16)
# byte_array = samples.tobytes()
# bits = np.unpackbits(np.frombuffer(byte_array, dtype=np.uint8))
# # Step 2: Convert bytes to numpy array of uint866
# #byte_array = np.frombuffer(frames, dtype=np.uint8)

# # Step 3: Convert bytes to bits (each byte → 8 bits)
# #bits = np.unpackbits(byte_array)

# print(bits)
# print("Total bits:", len(bits))


# bits=[1,0,1,0,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,0,1,0,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1,
#       1,0,1,0,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1,
#       1,0,1,0,1,0,1,1,0,0,1,1,0,0,1,1,0,0,1]


# bits=[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
bits=[0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
header_size=200
symbol_rate=441
samples_per_symbol=10
#parameters to be found
total_symbols=len(bits)
symbol_duration=1/symbol_rate
#total_samples=samples_per_symbol*total_symbols
packet_size=38 #interms of symbols
time_bet_msg=(header_size+packet_size)*symbol_duration
msg_time=0.75*time_bet_msg


#message_samples= int(packet_size*samples_per_symbol)
rest_time= time_bet_msg - msg_time
print(rest_time)
def bits_to_symbols(bitstream):
    mapping = {
        1: 0.1 + 0.1j,
        0: -0.1 - 0.1j }
    return np.array([mapping[b] for b in bitstream], dtype=complex)


symbols=bits_to_symbols(bits)
print("symbols prepared...",symbols)
header=np.tile(1+1j,header_size)
#header=header
data =np.concatenate((header,symbols))
print(len(data))
total_samples=(len(data))*samples_per_symbol
print("total samples:" ,total_samples)

sampling_rate=(((packet_size+header_size)*samples_per_symbol)/msg_time)

print("s_m", sampling_rate)

def packetize_symbol(sym):
    p_size=len(sym)
    n_= (p_size - len(sym) % p_size) % p_size
    sym = list(sym) + [0+ 0j] * n_
    packets = [sym[k:k+p_size] for k in range(0, len(sym), p_size)]
    return packets,n_

#message,extra=packetize_symbol(data)
#print(extra)
#print("total_messages:", len(message))
#print(message)
message=[]
message.append(data)
extra=0

transmit = []
sum=0
X=0
for pkt_bits in message:
    print(message)
    pulse = np.ones(samples_per_symbol)
    D = np.zeros(len(pkt_bits) * samples_per_symbol, dtype=complex)
    D[::samples_per_symbol] = pkt_bits
    x = np.convolve(D, pulse)
    T = np.zeros(len(x) * 2, dtype=np.float32)
    T[::2] = x.real
    T[1::2] = x.imag

    final =T[::2] + 1j * T[1::2]
    sum=sum+len(final)
    X=len(x)

    transmit.append(final)
    #time.sleep(rest_time)




# print(transmit)
# print(len(transmit))
# print(sum)
# print(X)






transmit = np.array(transmit, dtype=np.complex64)

center_freq= 2.4e9-1800-800-450
gain=70

print(len(transmit[0]))

sim.send_to_simulator(transmit,center_freq,sampling_rate,'node_1')

