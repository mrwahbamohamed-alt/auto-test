/**
 * pid_control.h  —  CamBox Pro V5
 * Closed-loop rail-pressure controller for the PCV valve (GPIO18).
 *   error  = target_bar - actual_bar
 *   output = Kp*error + Ki*integral + Kd*derivative   → PWM duty 0..255
 * Includes integral anti-windup (clamped to the 0..255 output range).
 */
#pragma once

#include <Arduino.h>

typedef struct {
    float Kp, Ki, Kd;
    float integral;
    float prev_error;
    bool  have_prev;     // false until first sample (avoids derivative kick)
} pid_state_t;

extern pid_state_t g_pid;

// Defaults from spec (tunable via serial `PID <Kp> <Ki> <Kd>`)
#define PID_KP_DEF   0.8f
#define PID_KI_DEF   0.05f
#define PID_KD_DEF   0.01f

#define PID_OUT_MIN   0.0f
#define PID_OUT_MAX 255.0f

void  pid_reset();
void  pid_set_gains(float kp, float ki, float kd);
// dt in seconds. Returns duty 0..255.
float pid_compute(float target_bar, float actual_bar, float dt);
