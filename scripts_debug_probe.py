import time
import wave

import vlc

wav_path = "/tmp/tone.wav"
with wave.open(wav_path, "w") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(8000)
    f.writeframes(b"\x00\x01" * 8000)

inst = vlc.Instance(["--aout=adummy", "--audio-visual=visual", "--effect-list=spectrum", "-vvv"])
mp = inst.media_player_new()
media = inst.media_new_path(wav_path)
mp.set_media(media)
mp.play()
for i in range(20):
    time.sleep(0.3)
    print(f"t={i*0.3:.1f} state={mp.get_state()} has_vout={mp.has_vout()}", flush=True)
mp.stop()
