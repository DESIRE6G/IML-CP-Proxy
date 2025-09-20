#include <core.p4>
#include <v1model.p4>
typedef bit<9> PortId_t;
typedef bit<32> digest_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
const bit<16> ETHERTYPE_IPV4 = 0x0800;
const bit<16> ETHERTYPE_ARP = 0x0806;
const bit<16> ETHERTYPE_VLAN = 0x8100;
const bit<8> IPPROTO_ICMP = 0x01;
const bit<8> IPPROTO_IPv4 = 0x04;
const bit<8> IPPROTO_TCP = 0x06;
const bit<8> IPPROTO_UDP = 0x11;
const bit<16> ARP_HTYPE_ETHERNET = 0x0001;
const bit<16> ARP_PTYPE_IPV4 = 0x0800;
const bit<8> ARP_HLEN_ETHERNET = 6;
const bit<8> ARP_PLEN_IPV4 = 4;
const bit<16> ARP_OPER_REQUEST = 1;
const bit<16> ARP_OPER_REPLY = 2;
const bit<8> ICMP_ECHO_REQUEST = 8;
const bit<8> ICMP_ECHO_REPLY = 0;
const bit<16> GTP_UDP_PORT = 2152;
const digest_t MAC_LEARN_RECEIVER = 1;
const digest_t ARP_LEARN_RECEIVER = 1025;
const macAddr_t OWN_MAC = 0x001122334455;
const macAddr_t BCAST_MAC = 0xFFFFFFFFFFFF;
const ip4Addr_t GW_IP = 0x0A000001;
header ethernet_t {
	 macAddr_t dstAddr;
	macAddr_t srcAddr;
	bit<16> etherType;
}
header ipv4_t {
	 bit<4> version;
	bit<4> ihl;
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
header icmp_t {
	 bit<8> type;
	bit<8> code;
	bit<16> checksum;
	bit<16> identifier;
	bit<16> sequence_number;
}
header udp_t {
	 bit<16> srcPort;
	bit<16> dstPort;
	bit<16> plength;
	bit<16> checksum;
}
header arp_t {
	 bit<16> htype;
	bit<16> ptype;
	bit<8> hlen;
	bit<8> plen;
	bit<16> oper;
}
header arp_ipv4_t {
	 macAddr_t sha;
	ip4Addr_t spa;
	macAddr_t tha;
	ip4Addr_t tpa;
}
header vlan_t {
	 bit<3> pcp;
	bit<1> cfi;
	bit<12> vid;
	bit<16> etherType;
}
header gtp_common_t {
	 bit<3> version;
	bit<1> pFlag;
	bit<1> tFlag;
	bit<1> eFlag;
	bit<1> sFlag;
	bit<1> pnFlag;
	bit<8> messageType;
	bit<16> messageLength;
}
header gtp_teid_t {
	 bit<32> teid;
}
header gtpv1_optional_t {
	 bit<16> sNumber;
	bit<8> pnNumber;
	bit<8> nextExtHdrType;
}
header gtpv1_extension_hdr_t {
	 bit<8> plength;
	bit<8> nextExtHdrType;
}
header gtpv2_ending_t {
	 bit<24> sNumber;
	bit<8> reserved;
}
header dissaggregation_header_t {
	 bit<8> ttl;
}
header dataneeded_header_t {
	 bit<1> needed;
	 bit<7> pad;
}
struct gtp_metadata_t {
	 bit<32> teid;
	bit<8> color;
}
struct arp_metadata_t {
	 ip4Addr_t dst_ipv4;
	macAddr_t mac_da;
	macAddr_t mac_sa;
	PortId_t egress_port;
	macAddr_t my_mac;
}
struct routing_metadata_t {
	 bit<8> nhgrp;
}
struct metadata {
	 gtp_metadata_t gtp_metadata;
	arp_metadata_t arp_metadata;
	routing_metadata_t routing_metadata;
}
struct headers {
	 dataneeded_header_t dataneeded_header;
	dissaggregation_header_t dissaggregation_header;
	ethernet_t ethernet;
	ipv4_t ipv4;
	ipv4_t inner_ipv4;
	icmp_t icmp;
	icmp_t inner_icmp;
	arp_t arp;
	arp_ipv4_t arp_ipv4;
	vlan_t vlan;
	gtp_common_t gtp_common;
	gtp_teid_t gtp_teid;
	gtpv1_extension_hdr_t gtpv1_extension_hdr;
	gtpv1_optional_t gtpv1_optional;
	gtpv2_ending_t gtpv2_ending;
	udp_t udp;
	udp_t inner_udp;
}
	parser ParserImpl(packet_in packet, out headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 state start {
		 packet.extract(hdr.ethernet);
		transition select(hdr.ethernet.etherType){
			 ETHERTYPE_IPV4 : parse_ipv4;
			ETHERTYPE_ARP : parse_arp;
			default : accept;
		}
	}
	state parse_arp {
		 packet.extract(hdr.arp);
		transition select(hdr.arp.htype, hdr.arp.ptype, hdr.arp.hlen, hdr.arp.plen){
			(ARP_HTYPE_ETHERNET, ARP_PTYPE_IPV4, ARP_HLEN_ETHERNET, ARP_PLEN_IPV4): parse_arp_ipv4;
			default : accept;
		}
	}
	state parse_arp_ipv4 {
		 packet.extract(hdr.arp_ipv4);
		meta.arp_metadata.dst_ipv4 = hdr.arp_ipv4.tpa;
		transition accept;
	}
	state parse_ipv4 {
		 packet.extract(hdr.ipv4);
		meta.arp_metadata.dst_ipv4 = hdr.ipv4.dstAddr;
		transition select(hdr.ipv4.protocol){
			 IPPROTO_ICMP : parse_icmp;
			IPPROTO_UDP : parse_udp;
			default : accept;
		}
	}
	state parse_icmp {
		 packet.extract(hdr.icmp);
		transition accept;
	}
	state parse_udp {
		 packet.extract(hdr.udp);
		transition select(hdr.udp.dstPort){
			 GTP_UDP_PORT : parse_gtp;
			default : accept;
		}
	}
	state parse_gtp {
		 packet.extract(hdr.gtp_common);
		transition select(hdr.gtp_common.version, hdr.gtp_common.tFlag){
			(1, 0): parse_teid;
			(1, 1): parse_teid;
			(2, 1): parse_teid;
			(2, 0): parse_gtpv2;
			default : accept;
		}
	}
	state parse_teid {
		 packet.extract(hdr.gtp_teid);
		transition parse_inner;
	}
	state parse_gtpv2 {
		 packet.extract(hdr.gtpv2_ending);
		transition accept;
	}
    state parse_inner {
        packet.extract(hdr.inner_ipv4);
        transition accept;
    }
}
control ingress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 meter(256, MeterType.bytes)teid_meters;
	action drop(){
		 mark_to_drop(standard_metadata);
	}
	action arp_digest(){
		 NoAction();
	}
	action arp_reply(){
		 hdr.ethernet.dstAddr = hdr.arp_ipv4.sha;
		hdr.ethernet.srcAddr = OWN_MAC;
		hdr.arp.oper = ARP_OPER_REPLY;
		hdr.arp_ipv4.tha = hdr.arp_ipv4.sha;
		hdr.arp_ipv4.tpa = hdr.arp_ipv4.spa;
		hdr.arp_ipv4.sha = OWN_MAC;
		hdr.arp_ipv4.spa = meta.arp_metadata.dst_ipv4;
		standard_metadata.egress_port =(PortId_t)(standard_metadata.ingress_port);
	}
	action send_icmp_reply(){
		 macAddr_t tmp_mac;
		ip4Addr_t tmp_ip;
		tmp_mac = hdr.ethernet.dstAddr;
		hdr.ethernet.dstAddr = hdr.ethernet.srcAddr;
		hdr.ethernet.srcAddr = tmp_mac;
		tmp_ip = hdr.ipv4.dstAddr;
		hdr.ipv4.dstAddr = hdr.ipv4.srcAddr;
		hdr.ipv4.srcAddr = tmp_ip;
		hdr.icmp.type = ICMP_ECHO_REPLY;
		hdr.icmp.checksum = 0;
		standard_metadata.egress_port =(PortId_t)(standard_metadata.ingress_port);
	}
	action set_nhgrp(bit<8> nhgrp){
		 meta.routing_metadata.nhgrp = nhgrp;
		hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
	}
		table ipv4_lpm {
		 key = {
			 hdr.ipv4.dstAddr : lpm;
		}
		actions = {
			 set_nhgrp;
			drop;
		}
		size = 256;
        default_action = set_nhgrp(1);
	}
	apply {
		 hdr.dataneeded_header.setValid();
		hdr.dataneeded_header.needed = 0;
		if(!(hdr.ethernet.isValid())){
			 return;
		}
			 if(hdr.arp.isValid()){
				 if((hdr.arp.oper == ARP_OPER_REQUEST)&& hdr.arp_ipv4.isValid()){
					 if((hdr.arp_ipv4.tpa == GW_IP)&&(! hdr.ipv4.isValid())&&(! hdr.icmp.isValid())){
						 arp_reply();
						return;
					}
					else {
						 }
				}
				else {
					 }
			}
			else {
				 }
					if((! hdr.arp.isValid())&&(! hdr.arp_ipv4.isValid())&& hdr.ipv4.isValid()){
				 if((hdr.ipv4.dstAddr == GW_IP)&& hdr.icmp.isValid()){
					 if((hdr.icmp.type == ICMP_ECHO_REQUEST)){
						 send_icmp_reply();
						return;
					}
					else {
						 }
				}
				else {
					 }
			}
			else {
				 }
			if(! hdr.ipv4.isValid()){
				 return;
			}
			if(! hdr.udp.isValid()){
				 return;
			}
			if(! hdr.gtp_teid.isValid()){
				 return;
			}
			NoAction();
			ipv4_lpm.apply();
			hdr.dissaggregation_header.setValid();
			hdr.dissaggregation_header.ttl = hdr.ipv4.ttl;
			hdr.dataneeded_header.needed = 1;
		    standard_metadata.egress_port = 2;
            standard_metadata.egress_spec = 2;

	}
}
	control DeparserImpl(packet_out packet, in headers hdr){
	 apply {
		 packet.emit(hdr.dataneeded_header);
		packet.emit(hdr.dissaggregation_header);
		packet.emit(hdr.ethernet);
		packet.emit(hdr.arp);
		packet.emit(hdr.arp_ipv4);
		packet.emit(hdr.ipv4);
		packet.emit(hdr.icmp);
		packet.emit(hdr.udp);
		packet.emit(hdr.gtp_common);
		packet.emit(hdr.gtp_teid);
	}
}
	control egress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 apply {
		 }
}
	control verifyChecksum(inout headers hdr, inout metadata meta){
	 apply {
		 }
}
	control computeChecksum(inout headers hdr, inout metadata meta){
	 apply {
		 }
}
V1Switch(ParserImpl(), verifyChecksum(), ingress(), egress(), computeChecksum(), DeparserImpl())main;
