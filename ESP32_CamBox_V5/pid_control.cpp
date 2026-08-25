/**
 * pid_control.cpp  —  CamBox Pro V5
 * PID with output clamping + integral anti-windup.
 */
#include "pid_control.h"

pid_state_t g_pid = {
    .Kp = PID_KP_DEF, .Ki = PID_KI_DEF, .Kd = PID_KD_DEF,
    .integral = 0.0f, .prev_error = 0.0f, .have_prev = false,
};

void pid_reset() {
    g_pid.integral   = 0.0f;
    g_pid.prev_error = 0.0f;
    g_pid.have_prev  = false;
}

void pid_set_gains(float kp, float ki, float kd) {
    g_pid.Kp = kp;
    g_pid.Ki = ki;
    g_pid.Kd = kd;
}

float pid_compute(float target_bar, float actual_bar, float dt) {
    if (dt <= 0.0f) dt = 0.01f;   // guard

    const float error = target_bar - actual_bar;

    // Derivative (skip on first sample → no derivative kick)
    float deriv = 0.0f;
    if (g_pid.have_prev) deriv = (error - g_pid.prev_error) / dt;
    g_pid.prev_error = error;
    g_pid.have_prev  = true;

    // Tentative integral
    float new_integral = g_pid.integral + error * dt;

    float output = g_pid.Kp * error
                 + g_pid.Ki * new_integral
                 + g_pid.Kd * deriv;

    // Clamp output and apply conditional anti-windup:
    // only commit the integral if we are NOT saturated in the same direction.
    if (output > PID_OUT_MAX) {
        output = PID_OUT_MAX;
        if (error < 0) g_pid.integral = new_integral;   // allow unwinding
    } else if (output < PID_OUT_MIN) {
        output = PID_OUT_MIN;
        if (error > 0) g_pid.integral = new_integral;   // allow unwinding
    } else {
        g_pid.integral = new_integral;                  // in range → accumulate
    }

    return output;
}
