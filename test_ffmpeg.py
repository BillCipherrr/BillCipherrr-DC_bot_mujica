
import discord
import sys

def test_ffmpeg():
    """
    Tests if discord.FFmpegPCMAudio can find and initialize FFmpeg.
    """
    # The path to the executable can be specified with the 'executable' parameter.
    # If left default, it will search for 'ffmpeg' in the system's PATH.
    executable = "ffmpeg"

    print(f"Attempting to initialize FFmpegPCMAudio with executable: '{executable}'")
    print("-" * 30)

    try:
        # We need a source, but it doesn't have to be a real file for this test.
        # The check for the executable happens during initialization.
        # Using a dummy file name is sufficient.
        audio_source = discord.FFmpegPCMAudio('dummy_source.mp3')

        print("\033[92mSuccess!\033[0m") # Green text for success
        print("discord.FFmpegPCMAudio was initialized successfully.")
        print("This means FFmpeg is correctly installed and accessible in your system's PATH.")

    except Exception as e:
        print("\033[91mError!\033[0m") # Red text for error
        print("An error occurred while trying to initialize FFmpegPCMAudio.")
        print(f"\nError details: {e}")
        print("\nThis likely means that FFmpeg is not installed or its location is not in the system's PATH.")
        print("Please ensure FFmpeg is installed correctly on your Mac.")
        print("You can install it using Homebrew with the command: brew install ffmpeg")

if __name__ == "__main__":
    # Check if discord.py is installed
    try:
        import discord
    except ImportError:
        print("\033[91mError!\033[0m")
        print("discord.py is not installed. Please install it using: pip install discord.py")
        sys.exit(1)

    test_ffmpeg()
