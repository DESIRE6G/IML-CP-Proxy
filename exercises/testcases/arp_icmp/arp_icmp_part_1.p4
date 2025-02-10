#include <core.p4>
#include <v1model.p4>
const bit<16> TYPE_IPV4 = 0x0800;
const bit<16> TYPE_ARP = 0x0806;
const bit<8> PROTO_ICMP = 1;
const bit<16> ARP_HTYPE = 0x0001;
const bit<16> ARP_PTYPE = TYPE_IPV4;
const bit<8> ARP_HLEN = 6;
const bit<8> ARP_PLEN = 4;
const bit<16> ARP_REQ = 1;
const bit<16> ARP_REPLY = 2;
typedef bit<9> egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
header ethernet_t {
	 macAddr_t dstAddr;
	macAddr_t srcAddr;
	bit<16> etherType;
}
header arp_t {
	 bit<16> h_type;
	bit<16> p_type;
	bit<8> h_len;
	bit<8> p_len;
	bit<16> op_code;
	macAddr_t src_mac;
	ip4Addr_t src_ip;
	macAddr_t dst_mac;
	ip4Addr_t dst_ip;
}
header icmp_t {
	 bit<8> icmp_type;
	bit<8> icmp_code;
	bit<16> checksum;
	bit<16> identifier;
	bit<16> sequence_number;
	varbit<1024> padding;
}
header ipv4_t {
	 bit<8> versionihl;
	bit<8> diffserv;
	bit<16> totalLen;
	bit<16> identification;
	bit<3> flags;
	bit<13> fragOffset;
	bit<8> ttl;
	bit<8> protocol;
	bit<16> hdrChecksum;
	ip4Addr_t srcAddr;
	ip4Addr_t dstAddr;
}
struct metadata {
	 }
struct headers {
	 ethernet_t ethernet;
	arp_t arp;
	ipv4_t ipv4;
	icmp_t icmp;
}
	parser MyParser(packet_in packet, out headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 state start {
		 packet.extract(hdr.ethernet);
		transition select(hdr.ethernet.etherType){
			 TYPE_ARP : parse_arp;
			TYPE_IPV4 : parse_ipv4;
			default : accept;
		}
	}
	state parse_arp {
		 packet.extract(hdr.arp);
		transition select(hdr.arp.op_code){
			 ARP_REQ : accept;
			default : accept;
		}
	}
	state parse_ipv4 {
		 packet.extract(hdr.ipv4);
		transition select(hdr.ipv4.protocol){
			 PROTO_ICMP : parse_icmp;
			default : accept;
		}
	}
	state parse_icmp {
		 bit<32> n =(bit<32>)(hdr.ipv4.totalLen)-(bit<32>)(hdr.ipv4.versionihl << 2);
		packet.extract(hdr.icmp, 8 * n - 64);
		transition accept;
	}
}
	control MyVerifyChecksum(inout headers hdr, inout metadata meta){
	 apply {
		 }
}
	control MyIngress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 action drop(){
		 mark_to_drop(standard_metadata);
	}
	action arp_reply(macAddr_t request_mac){
		 hdr.arp.op_code = ARP_REPLY;
		hdr.arp.dst_mac = hdr.arp.src_mac;
		hdr.arp.src_mac = request_mac;
        ip4Addr_t source_ip_temp =  hdr.arp.src_ip;
        hdr.arp.src_ip = hdr.arp.dst_ip;
        hdr.arp.dst_ip = source_ip_temp;
		hdr.ethernet.dstAddr = hdr.ethernet.srcAddr;
		hdr.ethernet.srcAddr = request_mac;


		standard_metadata.egress_spec = standard_metadata.ingress_port;
	}
		table arp_exact {
		 key = {
			 hdr.arp.dst_ip : exact;
		}
		actions = {
			 arp_reply;
			drop;
		}
		size = 1024;
		default_action = drop;
	}
    apply {
        if(standard_metadata.ingress_port == 2){
            standard_metadata.egress_spec = 1;
        }else{
            if(hdr.arp.isValid()){
                arp_exact.apply();
            }
            else if(hdr.icmp.isValid()){
                standard_metadata.egress_spec = 2;
            }
            else {
                drop();
            }
        }
	}
}
	control MyEgress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 apply {
		 }
}
		control MyComputeChecksum(inout headers hdr, inout metadata meta){
	 apply {
		 update_checksum(hdr.icmp.isValid(), {
			 hdr.icmp.icmp_type, hdr.icmp.icmp_code, 16w0, hdr.icmp.identifier, hdr.icmp.sequence_number, hdr.icmp.padding }
		, hdr.icmp.checksum, HashAlgorithm.csum16);
		update_checksum(hdr.ipv4.isValid(), {
			 hdr.ipv4.versionihl, hdr.ipv4.diffserv, hdr.ipv4.totalLen, hdr.ipv4.identification, hdr.ipv4.flags, hdr.ipv4.fragOffset, hdr.ipv4.ttl, hdr.ipv4.protocol, hdr.ipv4.srcAddr, hdr.ipv4.dstAddr }
		, hdr.ipv4.hdrChecksum, HashAlgorithm.csum16);
	}
}
	control MyDeparser(packet_out packet, in headers hdr){
	 apply {
		 packet.emit(hdr.ethernet);
		packet.emit(hdr.arp);
		packet.emit(hdr.ipv4);
		packet.emit(hdr.icmp);
	}
}
V1Switch(MyParser(), MyVerifyChecksum(), MyIngress(), MyEgress(), MyComputeChecksum(), MyDeparser())main;
