#include "tb_components.hh"
#include "tb_macros.hh"
#include <inttypes.h>
#include <fstream> 
#include <algorithm>

using std::copy;

// using std::ifstream;


ReqTx::ReqTx()
{
}

ReqTx::~ReqTx()
{
}

RspTx::RspTx()
{
}

RspTx::~RspTx()
{
}

Drv::Drv(Vaes_core *dut)
{
    this->dut = dut;
}

Drv::~Drv()
{
}

void Drv::drive(ReqTx *req)
{
    dut->load_i = 0;

    // #NOTA: come lo guido il load ? 
    // Otherwise, drive key and data in with the new request
    if (req != NULL && !dut->busy_o)
    {
        dut->load_i = req->aes_load;
        copy(req->key, req->key + 32, dut->key_i);
        copy(req->data_in, req->data_in + 16, dut->data_i); 
        dut->size_i = req->key_size;
        dut->dec_i = req->mode;
    }
}

Scb::Scb()
{
    this->tx_num = 0;
    this->err_num = 0;
}

Scb::~Scb()
{
}

void Scb::writeReq(ReqTx *req)
{
    this->req_q.push_back(req);
}

void Scb::writeRsp(RspTx *rsp)
{
    this->rsp_q.push_back(rsp);
    this->checkRes();
}

void Scb::checkRes()
{
    // Expected result
    vluint8_t exp_data_out[16] = {0};   // initialize to 0
    vluint8_t exp_key[32] = {0};        // initialize to 0
    
    // Read the expected result from the file "input_data.txt" 
    //ifstream inputFile("../input_data.txt"); 
  
    // Check if the file is successfully opened 
    //if (!inputFile.is_open()) { 
    //    TB_ERR("SCB > Error: File not Open");
    //    return 1; 
    //} 
 
    if (this->req_q.empty())
    {
        TB_ERR("SCB > Received response without request!");
    }

    ReqTx *req = this->req_q.front();
    this->req_q.pop_front();
    RspTx * rsp = this->rsp_q.front();
    this->rsp_q.pop_front();
    tx_num++;

    //int64_t rs1_int = (int64_t) req->rs1;
    //int64_t rs2_int = (int64_t) req->rs2;
    //
    //uint64_t rs1_w_int = (int32_t) req->rs1;
    //uint64_t rs2_w_int = (int32_t) req->rs2;

    // Check if the result is correct
    //exp_res = read_from_file 

    //if ( rsp->res != exp_res)
    //{
    //    TB_ERR("Received wrong result!");
    //    TB_ERR("RSP > op: %-5s rs1: 0x%016lx | rs2: 0x%016lx --> res: 0x%016lx (expected: 0x%016lx)", 
    //            op_str[req->alu_ctl], req->rs1, req->rs2, rsp->res, exp_res);
    //    err_num++;
    //}
    //else
    //{
    //    TB_SUCCESS(LOG_MEDIUM, "RSP > op: %-5s rs1: 0x%016lx | rs2: 0x%016lx --> res: 0x%016lx (expected: 0x%016lx)", 
    //            op_str[req->alu_ctl], req->rs1, req->rs2, rsp->res, exp_res);
    //}
    // Clean up
    TB_SUCCESS(LOG_MEDIUM, "ok");
    delete req;
    delete rsp;
}

unsigned int Scb::getTxNum()
{
    return this->tx_num;
}

unsigned int Scb::getErrNum()
{
    return this->err_num;
}

int Scb::isDone()
{
    return this->req_q.empty() && this->rsp_q.empty();
}

ReqMonitor::ReqMonitor(Vaes_core *dut, Scb *scb)
{
    this->dut = dut;
    this->scb = scb;
    this->req = NULL;
    this->req_busy = false; // reset request status
}

ReqMonitor::~ReqMonitor()
{
}

void ReqMonitor::monitor()
{
    // Check if there's a new request
    if (dut->load_i)
    {
        // Fetch the data from the DUT interface
        this->req = new ReqTx();
        copy(dut->key_i, dut->key_i + 32, this->req->key);
        copy(dut->data_i, dut->data_i + 16, this->req->data_in);
        this->req->key_size = dut->size_i;
        this->req->mode = dut->dec_i;
        // Send the request to the scoreboard
        scb->writeReq(this->req);

        // Print the request content
        // TODO: print the array content
        // TB_LOG(LOG_HIGH, "REQ > mode: %-5s | rs1:  0x%" PRIx64 " | rs2:  0x%" PRIx " ", op_str[this->req->alu_ctl], this->req->rs1, this->req->rs2);
    }
}

RspMonitor::RspMonitor(Vaes_core *dut, Scb *scb)
{
    this->dut = dut;
    this->scb = scb;
}

RspMonitor::~RspMonitor()
{
}

void RspMonitor::monitor()
{
    // Check if the DUT produced any response
    if (!dut->busy_o)
    {
        // Fetch the data from the DUT interface
        RspTx *rsp = new RspTx();
        copy(dut->data_o, dut->data_o + 16, rsp->data_out);
        scb->writeRsp(rsp);
    }
}