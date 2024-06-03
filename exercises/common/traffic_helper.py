from scapy.arch import get_if_list


def get_eth0_interface():
    for interface in get_if_list():
        if "eth0" in interface:
            return interface
    else:
        print("Cannot find eth0 interface")
        exit(1)

