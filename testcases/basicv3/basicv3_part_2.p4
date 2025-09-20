#include <core.p4>
#include <v1model.p4>
const bit<16> TYPE_IPV4 = 0x800;
typedef bit<9> egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
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
header dissaggregation_header_t {
	 egressSpec_t port;
	 	 bit<7> pad;

}
header dataneeded_header_t {
	 bit<1> needed;
	 	 bit<7> pad;

}
struct metadata {
	 egressSpec_t port;
}
struct headers {
	 dataneeded_header_t dataneeded_header;
	dissaggregation_header_t dissaggregation_header;
	ethernet_t ethernet;
	ipv4_t ipv4;
}
	parser MyParser(packet_in packet, out headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 state start {
		 packet.extract(hdr.dataneeded_header);
		transition select(hdr.dataneeded_header.needed){
			 1 : parse_dissaggregation_header_t;
			default : extract;
		}
	}
	state parse_dissaggregation_header_t {
		 packet.extract(hdr.dissaggregation_header);
		transition extract;
	}
	state extract {
		 packet.extract(hdr.ethernet);
		packet.extract(hdr.ipv4);
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
	action set_port(){
		 standard_metadata.egress_spec = meta.port;
		hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
	}
		table ipv4_lpm2 {
		 key = {
			 hdr.ipv4.dstAddr : lpm;
		}
		actions = {
			 set_port;
			NoAction;
		}
		size = 1024;
		default_action = NoAction();
	}
		table just_another {
		 key = {
			 hdr.ethernet.dstAddr : exact;
		}
		actions = {
			 drop;
			NoAction;
		}
		size = 1024;
		default_action = NoAction();
	}
		apply {
		 if(hdr.dataneeded_header.needed == 1){
			 meta.port = hdr.dissaggregation_header.port;
			ipv4_lpm2.apply();
		}
		else {
			 just_another.apply();
		}
	}
}
	control MyEgress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata){
	 apply {
		 }
}
	control MyComputeChecksum(inout headers hdr, inout metadata meta){
	 apply {
		 }
}
	control MyDeparser(packet_out packet, in headers hdr){
	 apply {
		 packet.emit(hdr.ethernet);
		packet.emit(hdr.ipv4);
	}
}
V1Switch(MyParser(), MyVerifyChecksum(), MyIngress(), MyEgress(), MyComputeChecksum(), MyDeparser())main;
