#include <core.p4>
#include <v1model.p4>
const bit<16> TYPE_IPV4 = 0x800;
typedef bit<9> egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
header ethernet_t{
	macAddr_t dstAddr;
	macAddr_t srcAddr;
	bit<16> etherType;
}

header ipv4_t{
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

header dissaggregation_header_1_t{
	egressSpec_t port;
    bit<7> pad;
}

struct metadata{
	egressSpec_t port;
}

struct headers{
	dissaggregation_header_1_t dissaggregation_header_1;
	ethernet_t ethernet;
	ipv4_t ipv4;
}

parser MyParser(packet_in packet,out headers hdr,inout metadata meta,inout standard_metadata_t standard_metadata){

	state start{
		packet.extract(hdr.dissaggregation_header_1);
		packet.extract(hdr.ethernet);
		packet.extract(hdr.ipv4);
		transition accept;
	}
}

control MyVerifyChecksum(inout headers hdr,inout metadata meta){
	apply{
	}
}

control MyIngress(inout headers hdr,inout metadata meta,inout standard_metadata_t standard_metadata){
	action set_port(){
		standard_metadata.egress_spec = meta.port;
		hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
	}

	table ipv4_lpm2{
		key ={
			hdr.ipv4.dstAddr : lpm;
		}

		actions ={
			set_port;
			NoAction;
		}

		size = 1024;
		default_action = NoAction();
	}

	apply{
		meta.port = hdr.dissaggregation_header_1.port;
		if(hdr.ethernet.etherType == TYPE_IPV4){
			ipv4_lpm2.apply();
		}

		else{
		}
	}
}

control MyEgress(inout headers hdr,inout metadata meta,inout standard_metadata_t standard_metadata){
	apply{
	}
}

control MyComputeChecksum(inout headers hdr,inout metadata meta){
	apply{
	}
}

control MyDeparser(packet_out packet,in headers hdr){
	apply{
		packet.emit(hdr.ethernet);
		packet.emit(hdr.ipv4);
	}
}

V1Switch(MyParser(),MyVerifyChecksum(),MyIngress(),MyEgress(),MyComputeChecksum(),MyDeparser())main;
