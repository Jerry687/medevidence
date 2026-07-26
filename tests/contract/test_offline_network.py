"""Contract checks for mandatory offline test execution."""

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_socket_creation_is_blocked() -> None:
    """pytest-socket must reject network-socket creation in this suite."""
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
