/*
    Author: Lorenzo Capobianco
    Date: 11/07/2025
    Description:
    This program performs the first round of the ASCON authenticated encryption algorithm for RV32I CPUs.
    In particular, the state registers are initialized with the key, nonce and the initialization vector.
    Then the first round of the ASCON algorithm is executed, which consists of an addition of a round constant,
    a substitution layer and a linear diffusion layer.
    At the end of the first round, the state registers 3 and 4 are used as new nonce value for the next iteration.
    There is no need to perform the full ASCON algorithm, as the goal is to collect power traces
    for the first round only, which is were the secret key is used, so that the
    power traces can be used for side-channel analysis.
    The program uses GPIO pins to trigger the scope and to read the trigger signal.
    The GPIO pin 3 is used to read the trigger signal, while GPIO pin 4
    is used to trigger the scope.
*/

#include <stdio.h>
#include <stdlib.h>

// --------- X-HEEP includes and defines ---------
#define XHEEP_PRINT 0

#include "core_v_mini_mcu.h"
#include "x-heep.h"
#include "gpio.h"

#define GPIO_INPUT_TRIGGER 3
#define GPIO_SCOPE_TRIGGER 4
// ----------------------------------------------

// Number of power traces collected for each iteration
#define POWER_TRACES 50000


int main() {
  // GPIO initialization. The program polls GPIO 3 for the trigger signal
  // and uses GPIO 4 to trigger the scope.
  gpio_result_t gpio_res;

  gpio_cfg_t pin_cfg3 = {
      .pin = GPIO_INPUT_TRIGGER,
      .mode = GpioModeIn,
      .en_input_sampling = true,
  };
  gpio_res = gpio_config (pin_cfg3);
  if (gpio_res != GpioOk){
      printf("Gpio %d initialization failed!\r\n", GPIO_INPUT_TRIGGER);
      return EXIT_FAILURE;
  }

  gpio_cfg_t pin_cfg4 = {
      .pin = GPIO_SCOPE_TRIGGER,
      .mode = GpioModeOutPushPull
  };
  gpio_res = gpio_config (pin_cfg4);
  if (gpio_res != GpioOk){
      printf("Gpio %d initialization failed!\r\n", GPIO_SCOPE_TRIGGER);
      return EXIT_FAILURE;
  }
  bool pin_value = 0;

  // Initial key and nonce value
  uint32_t k = 0x03020100;
  uint32_t n = 0x03020100;
  uint32_t res = 0;

  // Encryption loop
  for (int i = 0; i < POWER_TRACES; i++) {
  #if (defined XHEEP_PRINT) && (XHEEP_PRINT == 1)
    printf("input:\n");
    printf("k=%08x\n", k);
    printf("n=%08x\n", n);
  #endif
    // Wait for the trigger signal
    while (!pin_value) {
      gpio_read(GPIO_INPUT_TRIGGER, &pin_value);
    }
    // Trigger the scope
    gpio_write(GPIO_SCOPE_TRIGGER, 1);
    
    res = n ^ k;

    // Reset the trigger signal
    gpio_write(GPIO_SCOPE_TRIGGER, 0);
    // Wait for the trigger signal to go low again
    while (pin_value) {
      gpio_read(GPIO_INPUT_TRIGGER, &pin_value);
    }
  #if (defined XHEEP_PRINT) && (XHEEP_PRINT == 1)
    printf("output:\n");
    printf("k=%08x\n", k);
    printf("n=%08x\n", n);
    printf("res=%08x\n", res);
    printf("\n");
  #endif
    // Update the nonce for the next iteration
    n = res + 0xca31 + i;
  }

  exit(EXIT_SUCCESS);
}
