import stagehand
import inspect

print(f"Stagehand version/location: {stagehand.__file__}")
print("\nAttributes of stagehand module:")
print(dir(stagehand))

try:
    from stagehand import Stagehand
    print("\nAttributes of Stagehand class:")
    print(dir(Stagehand))
    
    # Try to see constructor arguments
    print("\nStagehand constructor signature:")
    print(inspect.signature(Stagehand.__init__))
except Exception as e:
    print(f"Error inspecting Stagehand class: {e}")
