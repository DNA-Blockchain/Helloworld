import json

task = {"runtime": "MicroPython", "task": "soft-launch"}
decoded = json.loads(json.dumps(task))

assert decoded["runtime"] == "MicroPython"
assert decoded["task"] == "soft-launch"

print("MicroPython task smoke passed:", decoded["task"])
