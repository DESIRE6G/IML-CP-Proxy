#include <core.p4>
#include <v1model.p4>

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;

header ethernet_t {
    macAddr_t dst_addr;
    macAddr_t src_addr;
    bit<16>   ether_type;
}

struct metadata {
    egressSpec_t port; 
}

header states_t {
    bit<8>    state1;
    bit<8>    state2;
    bit<8>    state3;
}

struct NF2_state_learn_digest_t {
    bit<8>    state1;
    bit<8>    state2;
    bit<8>    state3;
}

struct headers {
    ethernet_t   ethernet;
    states_t states;
}

struct NF1_mac_learn_digest_t {
    bit<48> src_addr;
    bit<9>  ingress_port;
}

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        packet.extract(hdr.ethernet);
        packet.extract(hdr.states);
        transition accept;
    }
}

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {   
    apply {  }
}

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    /*
    action NF1_mac_learn() {
        digest<NF1_mac_learn_digest_t>(1, {hdr.ethernet.src_addr, standard_metadata.ingress_port});
    }

    table NF1_smac {
        key = {
            hdr.ethernet.dst_addr: exact;
        }
        actions = {
            NF1_mac_learn;
            NoAction;
        }
        size = 1024;
        default_action = NF1_mac_learn;
    }
    */

    apply {
        // NF1_smac.apply();
        digest<NF2_state_learn_digest_t>(1, {hdr.states.state1, hdr.states.state2, hdr.states.state3});
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
        packet.emit(hdr.states);
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
