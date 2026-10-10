"""Publish live XINGYING/NOKOV motion-capture data as ROS 2 topics.

This bridge intentionally uses standard ROS 2 message types so it can be run
without first building a custom message package. NOKOV positions are reported
in millimetres by the supplied SDK and are converted to metres for ROS.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import math
import sys
import threading
import time
from collections import deque
from typing import Any

import rclpy
from builtin_interfaces.msg import Duration, Time
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Float32, UInt32
from visualization_msgs.msg import Marker, MarkerArray

from inspect_mocap import FrameInspector, point_is_valid
from nokov.nokovsdk import PySDKClient


MM_TO_M = 0.001
MARKER_LIFETIME = Duration(sec=0, nanosec=200_000_000)


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Publish XINGYING/NOKOV frames as ROS 2 topics."
    )
    parser.add_argument(
        "--server",
        default="10.1.1.198",
        help="XINGYING SDK server/NIC IPv4 address (default: %(default)s)",
    )
    parser.add_argument(
        "--world-frame",
        default="nokov_world",
        help="ROS frame_id attached to marker data (default: %(default)s)",
    )
    parser.add_argument(
        "--publish-period-ms",
        type=float,
        default=2.0,
        help="How often ROS checks for a new SDK frame (default: %(default)s)",
    )
    args, ros_args = parser.parse_known_args()
    if args.publish_period_ms <= 0:
        parser.error("--publish-period-ms must be greater than zero")
    return args, ros_args


class FrameQueue:
    """Buffer SDK frames briefly without blocking the native callback thread."""

    def __init__(self, max_frames: int = 512) -> None:
        self._lock = threading.Lock()
        self._snapshots: deque[dict[str, Any]] = deque(maxlen=max_frames)
        self.frames_received = 0
        self.frames_dropped = 0
        self.callback_errors = 0

    def __call__(self, frame_pointer: Any, _user_data: Any) -> None:
        if not frame_pointer:
            return
        try:
            snapshot = FrameInspector.frame_snapshot(frame_pointer.contents)
            with self._lock:
                if len(self._snapshots) == self._snapshots.maxlen:
                    self.frames_dropped += 1
                self._snapshots.append(snapshot)
                self.frames_received += 1
        except Exception as exc:  # exceptions must not escape a ctypes callback
            self.callback_errors += 1
            print(f"[SDK callback error] {type(exc).__name__}: {exc}", file=sys.stderr)

    def take_all(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshots = list(self._snapshots)
            self._snapshots.clear()
        return snapshots


class NokovRosBridge(Node):
    def __init__(self, server: str, world_frame: str, publish_period_ms: float) -> None:
        super().__init__("nokov_ros2_bridge")
        self.server = server
        self.world_frame = world_frame
        self.frame_queue = FrameQueue()
        self.client: PySDKClient | None = None
        self.frames_published = 0
        self._last_frame_number: int | None = None
        self._last_status_time = time.monotonic()

        self.frame_publisher = self.create_publisher(
            UInt32, "/nokov/frame_number", qos_profile_sensor_data
        )
        self.latency_publisher = self.create_publisher(
            Float32, "/nokov/latency_ms", qos_profile_sensor_data
        )
        self.labeled_count_publisher = self.create_publisher(
            UInt32, "/nokov/labeled_marker_count", qos_profile_sensor_data
        )
        self.unidentified_count_publisher = self.create_publisher(
            UInt32, "/nokov/unidentified_marker_count", qos_profile_sensor_data
        )
        self.rigid_count_publisher = self.create_publisher(
            UInt32, "/nokov/rigid_body_count", qos_profile_sensor_data
        )
        self.labeled_publisher = self.create_publisher(
            MarkerArray, "/nokov/labeled_markers", qos_profile_sensor_data
        )
        self.unidentified_publisher = self.create_publisher(
            MarkerArray, "/nokov/unidentified_markers", qos_profile_sensor_data
        )
        self.rigid_publisher = self.create_publisher(
            MarkerArray, "/nokov/rigid_bodies", qos_profile_sensor_data
        )

        self.timer = self.create_timer(publish_period_ms / 1000.0, self.publish_pending)

    def start_sdk(self) -> None:
        client = PySDKClient()
        version = ".".join(str(int(value)) for value in client.PyNokovVersion())
        self.get_logger().info(f"NOKOV SDK version: {version}")
        self.get_logger().info(f"Connecting to XINGYING SDK server: {self.server}")

        client.PySetVerbosityLevel(0)
        client.PySetMessageCallback(self._sdk_message_callback)
        result = client.Initialize(self.server.encode("utf-8"))
        if result != 0:
            raise RuntimeError(
                f"SDK connection failed with code {result}; check the wired NIC, "
                "XINGYING SDK Enabled setting, and Live Mode"
            )

        callback_result = client.PySetDataCallback(self.frame_queue, None)
        if callback_result != 0:
            raise RuntimeError(
                f"Registering the SDK data callback failed with code {callback_result}"
            )

        self.client = client
        self.get_logger().info("Connected; publishing live NOKOV frames as ROS 2 topics")

    @staticmethod
    def _sdk_message_callback(level: int, message_pointer: Any) -> None:
        raw = ctypes.cast(message_pointer, ctypes.c_char_p).value
        message = raw.decode("utf-8", errors="replace") if raw else ""
        if level <= 2:
            print(f"[SDK level={level}] {message}", file=sys.stderr)

    def publish_pending(self) -> None:
        # Windows may wake a short-period timer after more than one 90 Hz camera
        # frame. Drain the queue so those intermediate frames are not discarded.
        for snapshot in self.frame_queue.take_all():
            self.publish_snapshot(snapshot)

    def publish_snapshot(self, snapshot: dict[str, Any]) -> None:
        frame_number = int(snapshot["frame"])
        if frame_number == self._last_frame_number:
            return
        self._last_frame_number = frame_number
        timestamp_ms = int(snapshot["timestamp_ms"])
        stamp = Time(
            sec=timestamp_ms // 1000,
            nanosec=(timestamp_ms % 1000) * 1_000_000,
        )

        self.frame_publisher.publish(UInt32(data=frame_number))
        self.latency_publisher.publish(Float32(data=float(snapshot["latency"])))
        self.labeled_count_publisher.publish(
            UInt32(data=int(snapshot["counts"]["labeled_markers"]))
        )
        self.unidentified_count_publisher.publish(
            UInt32(data=int(snapshot["counts"]["unidentified_markers"]))
        )
        self.rigid_count_publisher.publish(
            UInt32(data=int(snapshot["counts"]["rigid_bodies"]))
        )

        labeled = MarkerArray()
        for point in snapshot["labeled_markers"]:
            if not point["valid"]:
                continue
            size_m = max(float(point["size"]) * MM_TO_M, 0.005)
            labeled.markers.append(
                self._point_marker(
                    stamp=stamp,
                    namespace="labeled_markers",
                    marker_id=int(point["id"]),
                    xyz_mm=point["xyz_mm"],
                    diameter_m=size_m,
                    color=(0.0, 0.8, 1.0, 1.0),
                )
            )
        self.labeled_publisher.publish(labeled)

        unidentified = MarkerArray()
        for point in snapshot["unidentified_markers"]:
            if not point["valid"]:
                continue
            unidentified.markers.append(
                self._point_marker(
                    stamp=stamp,
                    namespace="unidentified_markers",
                    marker_id=int(point["index"]),
                    xyz_mm=point["xyz_mm"],
                    diameter_m=0.01,
                    color=(1.0, 0.8, 0.0, 1.0),
                )
            )
        self.unidentified_publisher.publish(unidentified)

        rigid_bodies = MarkerArray()
        for body in snapshot["rigid_bodies"]:
            position = [float(value) for value in body["position_mm"]]
            orientation = [float(value) for value in body["orientation_xyzw"]]
            if not point_is_valid(position) or not all(
                math.isfinite(value) for value in orientation
            ):
                continue
            rigid_bodies.markers.append(self._rigid_marker(stamp, body))
        self.rigid_publisher.publish(rigid_bodies)

        self.frames_published += 1
        now = time.monotonic()
        if now - self._last_status_time >= 1.0:
            self.get_logger().info(
                f"frame={frame_number} labeled={len(labeled.markers)} "
                f"unidentified={len(unidentified.markers)} "
                f"rigid_bodies={len(rigid_bodies.markers)} "
                f"latency_ms={float(snapshot['latency']):.3f}"
            )
            self._last_status_time = now

    def _point_marker(
        self,
        *,
        stamp: Any,
        namespace: str,
        marker_id: int,
        xyz_mm: list[float],
        diameter_m: float,
        color: tuple[float, float, float, float],
    ) -> Marker:
        marker = Marker()
        marker.header.stamp = stamp
        marker.header.frame_id = self.world_frame
        marker.ns = namespace
        marker.id = marker_id
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD
        marker.pose.position.x = float(xyz_mm[0]) * MM_TO_M
        marker.pose.position.y = float(xyz_mm[1]) * MM_TO_M
        marker.pose.position.z = float(xyz_mm[2]) * MM_TO_M
        marker.pose.orientation.w = 1.0
        marker.scale.x = diameter_m
        marker.scale.y = diameter_m
        marker.scale.z = diameter_m
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = color
        marker.lifetime = MARKER_LIFETIME
        return marker

    def _rigid_marker(self, stamp: Any, body: dict[str, Any]) -> Marker:
        marker = Marker()
        marker.header.stamp = stamp
        marker.header.frame_id = self.world_frame
        marker.ns = "rigid_bodies"
        marker.id = int(body["id"])
        marker.type = Marker.ARROW
        marker.action = Marker.ADD
        marker.pose.position.x = float(body["position_mm"][0]) * MM_TO_M
        marker.pose.position.y = float(body["position_mm"][1]) * MM_TO_M
        marker.pose.position.z = float(body["position_mm"][2]) * MM_TO_M
        marker.pose.orientation.x = float(body["orientation_xyzw"][0])
        marker.pose.orientation.y = float(body["orientation_xyzw"][1])
        marker.pose.orientation.z = float(body["orientation_xyzw"][2])
        marker.pose.orientation.w = float(body["orientation_xyzw"][3])
        marker.scale.x = 0.10
        marker.scale.y = 0.02
        marker.scale.z = 0.02
        marker.color.r = 1.0
        marker.color.g = 0.2
        marker.color.b = 0.2
        marker.color.a = 1.0
        marker.lifetime = MARKER_LIFETIME
        return marker

    def stop_sdk(self) -> None:
        client = self.client
        self.client = None
        if client is not None:
            del client
            gc.collect()


def main() -> int:
    args, ros_args = parse_args()
    rclpy.init(args=ros_args)
    node = NokovRosBridge(args.server, args.world_frame, args.publish_period_ms)
    exit_code = 0
    try:
        node.start_sdk()
        rclpy.spin(node)
    except KeyboardInterrupt:
        # rclpy's Windows signal handler may already have invalidated the
        # context, in which case publishing this line to rosout would warn.
        if rclpy.ok():
            node.get_logger().info("Stopping on Ctrl+C")
        else:
            print("Stopping on Ctrl+C")
    except Exception as exc:
        node.get_logger().error(str(exc))
        exit_code = 1
    finally:
        node.stop_sdk()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    print(
        f"Stopped. SDK frames received: {node.frame_queue.frames_received}; "
        f"ROS frames published: {node.frames_published}; "
        f"queue-overflow drops: {node.frame_queue.frames_dropped}; "
        f"callback errors: {node.frame_queue.callback_errors}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
