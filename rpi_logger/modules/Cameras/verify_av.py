import av
from fractions import Fraction

try:
    container = av.open("test.mp4", "w")
    fps = 30.0
    
    print("Testing with float...")
    try:
        stream = container.add_stream("libx264", rate=fps)
        print("Success with float (unexpected)")
    except Exception as e:
        print(f"Failed with float as expected: {e}")

    print("Testing with Fraction...")
    try:
        rate = Fraction(fps).limit_denominator()
        stream = container.add_stream("libx264", rate=rate)
        print("Success with Fraction")
    except Exception as e:
        print(f"Failed with Fraction: {e}")
        
    container.close()
except Exception as e:
    print(f"General error: {e}")
