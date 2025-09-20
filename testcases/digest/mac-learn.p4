#include <core.p4>
#include <v1model.p4>

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

struct metadata {
    egressSpec_t port; 
}

struct headers {
    ethernet_t   ethernet;
}

struct mac_learn_digest_t {
    bit<48> srcAddr;
    bit<9>  ingress_port;
}

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        packet.extract(hdr.ethernet);
        transition accept;
    }


}

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {   
    apply {  }
}

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    action mac_learn() {
        digest<mac_learn_digest_t>(1, {hdr.ethernet.srcAddr, standard_metadata.ingress_port});
    }

    table smac {
        key = {
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            mac_learn;
            NoAction;
        }
        size = 1024;
        default_action = mac_learn;
    }

    apply {
        smac.apply();
        standard_metadata.egress_spec = 2 - standard_metadata.ingress_port + 1;
    }
}

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {  }
}

control MyComputeChecksum(inout headers  hdr, inout metadata meta) {
     apply { }
}

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
    }
}

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
