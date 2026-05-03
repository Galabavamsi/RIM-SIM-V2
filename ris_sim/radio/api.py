"""SDR-like client API for the RIS emulator.

These functions connect to a running :class:`SimulationServer` via ZeroMQ
and provide blocking send/receive semantics that mimic USRP API calls.

Usage::

    from ris_sim.radio.api import send_to_simulator, receive_from_simulator

    send_to_simulator(iq_samples, fc=2.4e9, sample_rate=5880, node_id="node_1")
    result = receive_from_simulator(120, fc=2.4e9, sample_rate=5880, node_id="node_2")
    # result is a complex np.ndarray of 120 IQ samples
"""

from __future__ import annotations


import numpy as np

from ris_sim.io.transport import ClientTransport, TransportError, DEFAULT_SERVER_ADDR


def send_to_simulator(
    data: np.ndarray | list,
    fc: float,
    sample_rate: float,
    node_id: str,
    *,
    tau: float = 0.002,
    server_addr: str = DEFAULT_SERVER_ADDR,
    timeout: float = 30.0,
) -> str:
    """Send IQ samples to the emulator for transmission.

    Args:
        data: Complex ndarray or list of [I, Q] pairs.
        fc: Center frequency in Hz.
        sample_rate: Sample rate in Hz.
        node_id: Target node ID.
        tau: Tick duration in seconds.
        server_addr: ZeroMQ server address.
        timeout: Request timeout in seconds.

    Returns:
        request_id: Unique ID for tracking this transmission.
    """
    transport = ClientTransport(server_addr)

    if isinstance(data, np.ndarray):
        if np.iscomplexobj(data):
            iq_list = [[float(v.real), float(v.imag)] for v in data.ravel()]
        else:
            iq_list = data.tolist()
    else:
        iq_list = list(data)

    response = transport.request(
        {
            "cmd": "tx",
            "node_id": node_id,
            "fc": fc,
            "sample_rate": sample_rate,
            "tau": tau,
            "data": iq_list,
        },
        timeout_ms=int(timeout * 1000),
    )

    transport.close()
    if response.get("status") == "error":
        raise TransportError(response.get("message", "Unknown TX error"))
    return response["request_id"]


def receive_from_simulator(
    num_samps: int,
    fc: float,
    sample_rate: float,
    node_id: str,
    *,
    tau: float = 0.002,
    server_addr: str = DEFAULT_SERVER_ADDR,
    timeout: float = 30.0,
) -> np.ndarray:
    """Receive IQ samples from the emulator. Blocks until data is ready.

    Args:
        num_samps: Number of IQ samples to receive.
        fc: Center frequency in Hz.
        sample_rate: Sample rate in Hz.
        node_id: Target node ID.
        tau: Tick duration in seconds.
        server_addr: ZeroMQ server address.
        timeout: Request timeout in seconds.

    Returns:
        Complex ndarray of received IQ samples.
    """
    transport = ClientTransport(server_addr)

    response = transport.request(
        {
            "cmd": "rx",
            "node_id": node_id,
            "fc": fc,
            "sample_rate": sample_rate,
            "num_samps": num_samps,
            "tau": tau,
            "timeout": timeout,
        },
        timeout_ms=int((timeout + 5) * 1000),  # extra margin for simulation time
    )

    transport.close()
    if response.get("status") == "error":
        raise TransportError(response.get("message", "Unknown RX error"))

    data = response["data"]
    return np.array([complex(v[0], v[1]) for v in data], dtype=np.complex128)


def check_available_tx(fc: float, server_addr: str = DEFAULT_SERVER_ADDR) -> list[str]:
    """Check which nodes are currently transmitting on a given frequency."""
    transport = ClientTransport(server_addr)
    response = transport.request({"cmd": "status"}, timeout_ms=5000)
    transport.close()

    if response.get("status") != "ok":
        return []
    return [
        n["id"] for n in response.get("nodes", [])
        if n["mode"] == "transmit"
    ]


def get_node_location(node_id: str, server_addr: str = DEFAULT_SERVER_ADDR) -> list[float]:
    """Get the current location of a node."""
    transport = ClientTransport(server_addr)
    response = transport.request({"cmd": "status"}, timeout_ms=5000)
    transport.close()

    if response.get("status") != "ok":
        return [0.0, 0.0, 0.0]
    for n in response.get("nodes", []):
        if n["id"] == node_id:
            return list(n["location"])
    return [0.0, 0.0, 0.0]


def ris_set_config(
    ris_id: str,
    matrix: list[list[float]],
    *,
    server_addr: str = DEFAULT_SERVER_ADDR,
    timeout: float = 5.0,
) -> None:
    """Update a RIS panel configuration on a running server.

    Args:
        ris_id: RIS panel ID.
        matrix: (M, N) list of element states.
        server_addr: ZeroMQ server address.
        timeout: Request timeout in seconds.
    """
    transport = ClientTransport(server_addr)
    response = transport.request(
        {"cmd": "ris_config", "ris_id": ris_id, "matrix": matrix},
        timeout_ms=int(timeout * 1000),
    )
    transport.close()
    if response.get("status") != "ok":
        raise TransportError(response.get("message", "Unknown RIS config error"))
