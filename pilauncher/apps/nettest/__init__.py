"""Tester rete: diagnostica della presa Ethernet per l'helpdesk.

Collegando il cavo parte da solo: link, switch e porta (LLDP/CDP), 802.1X, DHCP, gateway, DNS, Internet.
Strumenti: ping continuo, rinnovo DHCP, lampeggio della porta sullo switch, test del cavo, risoluzione DNS.
"""
from .main import APP  # noqa: F401
