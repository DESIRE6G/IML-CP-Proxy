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

header dissaggregation_header_2_t{
	macAddr_t dstAddr;
}

struct metadata{
	egressSpec_t port;
	egressSpec_t selector;
}

struct headers{
	dissaggregation_header_2_t dissaggregation_header_2;
	dissaggregation_header_1_t dissaggregation_header_1;
	ethernet_t ethernet;
	ipv4_t ipv4;
}

parser MyParser(packet_in packet,out headers hdr,inout metadata meta,inout standard_metadata_t standard_metadata){
	state start{
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
	action drop(){
		mark_to_drop(standard_metadata);
	}

	action chg_addr(egressSpec_t port,macAddr_t dstAddr){
		hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
		hdr.ethernet.dstAddr = dstAddr;
		meta.port = port;
	}

	table ipv4_lpm1{
		key ={
			hdr.ipv4.dstAddr : lpm;
		}

		actions ={
			chg_addr;
			drop;
			NoAction;
		}

		size = 1024;
		default_action = drop();
	}

	action set_out_port(egressSpec_t port){
		standard_metadata.egress_spec = port;
	}

	table selector_table{
		key ={
			meta.selector : exact;
		}

		actions ={
			set_out_port;
			NoAction;
		}

		size = 1024;
		default_action = NoAction();
	}

	apply{
		ipv4_lpm1.apply();
		if(hdr.ethernet.etherType == TYPE_IPV4){
			hdr.dissaggregation_header_1.setValid();
			hdr.dissaggregation_header_1.port = meta.port;
			meta.selector = 1;
		}

		else{
			hdr.dissaggregation_header_2.setValid();
			hdr.dissaggregation_header_2.dstAddr = hdr.ethernet.dstAddr;
			meta.selector = 2;
		}

		selector_table.apply();
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
		packet.emit(hdr.dissaggregation_header_2);
		packet.emit(hdr.dissaggregation_header_1);
		packet.emit(hdr.ethernet);
		packet.emit(hdr.ipv4);
	}
}

V1Switch(MyParser(),MyVerifyChecksum(),MyIngress(),MyEgress(),MyComputeChecksum(),MyDeparser())main;
