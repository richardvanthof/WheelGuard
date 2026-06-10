import requests
import time

class MonsterBorgClient(object):

    def __init__(self,
                 host,
                 api_key,
                 port=8443):

        self.base_url = \
            "http://{}:{}".format(host, port)

        self.headers = {
            "X-API-Key": api_key
        }

    # =====================================================
    # Low-Level Drive
    # =====================================================

    def drive(self, left, right):

        print(
            f"[DRIVE] "
            f"left={left:.3f} "
            f"right={right:.3f}"
        )

        try:

            response = requests.post(
                self.base_url + "/drive",
                headers=self.headers,
                json={
                    "left": left,
                    "right": right
                },
                timeout=2
            )

            print(
                f"[DRIVE] HTTP {response.status_code}"
            )

            return response

        except Exception as e:

            print(
                f"[DRIVE] FAILED: {e}"
            )

            raise
        
    # =====================================================
    # Timed Drive Primitive
    # =====================================================

    def drive_for(self,
                  left,
                  right,
                  duration):

        self.drive(left, right)

        time.sleep(duration)

        self.stop()

    # =====================================================
    # Stop
    # =====================================================

    def stop(self):

        return requests.post(

            self.base_url + "/stop",

            headers=self.headers
        )

    # =====================================================
    # Bark
    # =====================================================

    def bark(self):

        return requests.post(

            self.base_url + "/bark",

            headers=self.headers
        )


    # =====================================================
    # Directional Helpers
    # =====================================================

    def forward(self,
                left_power,
                right_power,
                duration):

        self.drive_for(
            abs(left_power),
            abs(right_power),
            duration
        )

    def backward(self,
                 left_power,
                 right_power,
                 duration):

        self.drive_for(
            -abs(left_power),
            -abs(right_power),
            duration
        )

    def left(self,
             left_power,
             right_power,
             duration):

        self.drive_for(
            abs(left_power),
            -abs(right_power),
            duration
        )

    def right(self,
              left_power,
              right_power,
              duration):

        self.drive_for(
            -abs(left_power),
            abs(right_power),
            duration
        )

    # =====================================================
    # Arcade Drive
    # =====================================================

    def arcade(self,
               forward,
               turn,
               duration):

        left = forward - turn
        right = forward + turn

        left = max(-1.0, min(1.0, left))
        right = max(-1.0, min(1.0, right))

        self.drive_for(
            left,
            right,
            duration
        )

    # =====================================================
    # Options
    # =====================================================

    def option(self, option_id):

        return requests.post(

            self.base_url +
            "/option/{}".format(option_id),

            headers=self.headers
        )