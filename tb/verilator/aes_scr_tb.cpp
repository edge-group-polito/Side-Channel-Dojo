// Copyright 2024 Politecnico di Torino.
// Copyright and related rights are licensed under the Solderpad Hardware
// License, Version 2.0 (the "License"); you may not use this file except in
// compliance with the License. You may obtain a copy of the License at
// http://solderpad.org/licenses/SHL-2.0. Unless required by applicable law
// or agreed to in writing, software, hardware and materials distributed under
// this License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the
// specific language governing permissions and limitations under the License.
//
// File: aes_scr_tb.cpp
// Author: Mattia Mirigaldi
// Date: 06/06/2024
// Description: testbench for AES SCA resilient

#include <cstdlib>
#include <cstdio>
#include <getopt.h>
#include <string> 
#include <fstream>
#include <verilated.h>           // Include Verilator common routines
#include <verilated_fst_c.h>     // Include the FST tracing class

#include "Vaes_core.h"
#include "tb_components.hh"     // Interface functions
#include "tb_macros.hh"         // Testbench logger

// Default parameters
#define RESET_CYCLES 10
#define FST_FILENAME "logs/waves.fst"
#define TRACE_FILENAME "logs/trace.log" 
#define MAX_SIM_TIME 1e7

using std::ifstream;

// Logger
TbLogger logger;

// Simulation cycles
vluint64_t sim_cycles = 0;

// Function prototypes
void clkGen(Vaes_core *dut);

// Input transaction object
ReqTx *genReqTx(); 

// Main function
int main(int argc, char *argv[]) {
    // Define command line options
    const option longopts[] = {
        {"max_cycles",  required_argument, NULL, 'c'},
        {"dump_waves",  required_argument, NULL, 'w'},
        {"dump_trace",  required_argument, NULL, 't'},
        {"log_level",   required_argument, NULL, 'l'},
        {"help",        no_argument,       NULL, 'h'},
        {NULL, 0, NULL, 0}
    };

    // Parse command line options
    // --------------------------
    bool              dump_waves = false;
    bool              dump_trace = false;
    unsigned long int max_cycles = ((unsigned long int) MAX_SIM_TIME) >> 1;
    int     opt;
    while ((opt = getopt_long(argc, argv, "c:l:w:t:h", longopts, NULL)) >= 0) {
        switch (opt) {
            case 'c':
                max_cycles = strtoul(optarg, NULL, 0);
                break;
            case 'l':
                logger.setLogLvl(optarg);
                break;
            case 'w':
                if (!strcmp(optarg, "true") || !strcmp(optarg, "1")) {
                    dump_waves = true;
                }
                break;
            case 't':
                if (!strcmp(optarg, "true") || !strcmp(optarg, "1")) {
                    dump_trace = true;
                }
                break;
            case 'h':
                printf("Usage: %s [OPTIONS]\n", argv[0]);
                printf("Options:\n");
                printf("  -c, --max_cycles <cycles>        Set maximum simulation cycles\n");
                printf("  -w, --dump_waves <true|false>    Enable waveform dump\n");
                printf("  -t, --dump_trace <true|false>    Enable instruction trace dump\n");
                printf("  -h, --help                       Show this help message\n");
                exit(EXIT_SUCCESS);
                break;
            default:
                // Skip SystemVerilog arguments
                fprintf(stderr, "ERROR: Unrecognized option. Use -h or --help for help\n", argv[optind]);
                exit(EXIT_FAILURE);
        }
    }

    // Print simulation configuration
    TB_CONFIG("Log level set to %u", logger.getLogLvl());
    TB_CONFIG("Reset cycles: %u", RESET_CYCLES);
    TB_CONFIG("Max simulation time: %u", max_cycles);
    TB_CONFIG("Wave dump: %s", dump_waves ? "ENABLED" : "DISABLED");
    if (dump_waves) TB_CONFIG("Wave dump file: %s", FST_FILENAME);
    TB_CONFIG("Instruction trace dump: %s", dump_trace ? "ENABLED" : "DISABLED");
    if (dump_trace) TB_CONFIG("Instruction trace file: %s", TRACE_FILENAME);

    // Simulation options
    unsigned long prg_seed = time(NULL);
    
    // Create simulation context
    VerilatedContext *cntx = new VerilatedContext;
    cntx->commandArgs(argc, argv);

    // Create log directory
    Verilated::mkdir("logs");

    // Pass simulation context to the logger
    logger.setSimContext(cntx);

    // Instantiate the DUT
    Vaes_core *dut = new Vaes_core(cntx);

    // FST trace file
    if (dump_waves) cntx->traceEverOn(true);
    VerilatedFstC *m_trace = new VerilatedFstC;
    if (dump_waves) {
        dut->trace(m_trace, 5); // Limit to 5 levels of hierarchy
        m_trace->open(FST_FILENAME);
    }

    // Open input file (contains key and data)
    //ifstream inputFile("../misc/input_data.txt");
    // check if the file has been opened properly
//    if (!inputFile.is_open() {
//        // print error message
//        fprintf(stderr, "ERROR: while opening input file\n");
//        exit(EXIT_FAILURE);
//    }
    
    // TB components
    Drv *drv = new Drv(dut);    // Driver
    Scb *scb = new Scb();       // Scoreboard
    ReqMonitor *reqMon = new ReqMonitor(dut, scb);
    RspMonitor *rspMon = new RspMonitor(dut, scb);

    // Request transaction initialization
    ReqTx *req = NULL;   

    // Initialiaze PRG
    TB_CONFIG("PRG seed: %u", prg_seed);
    srand(prg_seed);
    cntx->randSeed(prg_seed);
    
    // Start simulation
    long unsigned int sim_time = 0;
    long unsigned int sim_cycles = 0;
    TB_LOG(LOG_LOW, "Starting simulation...");
    while (!cntx->gotFinish() && cntx->time() < (max_cycles << 1))
    {
        // Generate clock 
        clkGen(dut);

        // Evaluate simulation step
        dut->eval();
        
        // Check if initial reset time is over
        if (dut->clk == 1 && cntx->time() > RESET_CYCLES)
        {
            // Generate a request
            req = genReqTx();
            if (req != NULL)
            {
                // Drive the DUT
                drv->drive(req);
                // reset req value
                req = NULL;
            }

            // Monitor inputs and outputs   
            reqMon->monitor();
            rspMon->monitor();
        }

        // Dump waveforms 
        if (dump_waves) m_trace->dump(cntx->time());

        // Increment simulation time
        cntx->timeInc(1);
        if (dut->clk == 1) sim_cycles++;
    }
    
    // Run post-simulation tasks
    dut->final();

    // Print simulation summary
    if (scb->getErrNum() > 0)
    {
        TB_ERR("TEST FAILED > errors: %u/%u", scb->getErrNum(), scb->getTxNum());
    }
    else 
    {
        TB_SUCCESS(LOG_LOW, "TEST SUCCEEDED > errors: %u/%u", scb->getErrNum(), scb->getTxNum());
    }
    
    // Clean up and exit
    m_trace->close();
    delete dut;
    delete cntx;
    return 0;
}

    // Clock generator
    void clkGen(Vaes_core *dut) {
        dut->clk ^= 1;
    }

    /*Generate an input transaction
      Return a req object */
    //ReqTx* genReqTx(ifstream &file)
    ReqTx* genReqTx()
    {
        // Create new transaction
        ReqTx *req = new ReqTx;
        // String to store each line of the file. 
        //string line; 
        
        req->aes_load = 1;
        req->key_size = 0;  //128 bits
        req->mode = 0;      //encrypt

        for (int i = 0; i < 32; i++)
        {
            req->key[i] = vl_rand64();
            if (i < 16)
            {
                req->data_in[i] = vl_rand64();
            }
            //// Read the line from the file
            //getline(file, line);
            //// Convert the string to an integer
            //req->key[i] = stoi(line, 0, 16);
        }
        return req; 
    }