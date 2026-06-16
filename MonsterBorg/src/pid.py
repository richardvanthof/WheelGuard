class PIDController:
    def __init__(self, Kp: float, Ki: float, Kd: float, setpoint: float = 0.0) -> None:
        self.Kp: float = Kp
        self.Ki: float = Ki
        self.Kd: float = Kd
        self.setpoint: float = setpoint
        self._integral: float = 0.0
        self._previous_error: float = 0.0

    def update(self, current_value: float, delta_time: float) -> float:
        error = self.setpoint - current_value
        p = self.Kp * error
        
        self._integral += error * delta_time
        i = self.Ki * self._integral
        
        if delta_time > 0:
            derivative: float = (error - self._previous_error) / delta_time
        else:
            derivative = 0.0
            
        d = self.Kd * derivative
        
        self._previous_error = error
        return p + i + d

    def reset(self) -> None:
        self._integral = 0.0
        self._previous_error = 0.0