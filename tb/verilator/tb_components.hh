#if !defined(AES_TB_COMPONENTS_HH_)
#define AES_TB_COMPONENTS_HH_

#include <verilated.h>
#include "Vaes_core.h"

class ReqTx
{
public:
    vluint8_t aes_load; 
    vluint8_t key[32];          // key is 32 bytes, 256 bits
    vluint8_t data_in[16];      // data_in is 16 bytes, 128 bits
    vluint8_t key_size;         // key could be 128, 192 or 256 bits long
    vluint8_t mode;             // 0 encrypt, 1 decrypt

    ReqTx();
    ~ReqTx();
};

class RspTx
{
public:
    vluint8_t data_out[16];
    vluint8_t busy;

    RspTx();
    ~RspTx();
};

class Drv
{
private:
    Vaes_core *dut;

public:
    Drv(Vaes_core *dut);
    ~Drv();

    void drive(ReqTx *req);
};

class Scb
{
private:
    std::deque<ReqTx *> req_q;
    std::deque<RspTx *> rsp_q;
    unsigned int tx_num;
    unsigned int err_num;

    void checkRes();
    
public:
    Scb();
    ~Scb();

    void writeReq(ReqTx *req);
    void writeRsp(RspTx *rsp);
    void flush();

    unsigned int getTxNum();
    unsigned int getErrNum();
    int isDone();
};

class ReqMonitor
{
private:
    Vaes_core *dut;
    Scb *scb;
    ReqTx *req;
    uint8_t req_busy;

public:
    ReqMonitor(Vaes_core *dut, Scb *scb);
    ~ReqMonitor();

    void monitor();
};

class RspMonitor
{
private:
    Vaes_core *dut;
    Scb *scb;

public:
    RspMonitor(Vaes_core *dut, Scb *scb);
    ~RspMonitor();

    void monitor();
};

#endif // AES_TB_COMPONENTS_HH_
