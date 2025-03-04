import atexit
import sys
import os
import time
import serial
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QFileDialog, \
    QProgressBar
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict_and_save, Model
from mido import MidiFile
from music21 import converter, note, chord, midi, stream


def send_midi_to_arduino_bulk(midi_file, max_notes=64):  # Set a maximum number of notes to send
    try:
        # Initialize serial connection to Arduino
        print("Attempting to connect to Arduino...")
        arduino = serial.Serial('COM13', 9600, timeout=1)  # Ensure the correct port is used
        time.sleep(2)  # Allow time for Arduino to reset
        print("Connected to Arduino!")

        mf = MidiFile(midi_file)
        print(f"Loaded MIDI file: {midi_file}")

        note_data = []  # Store the notes and their corresponding durations

        # Loop through each track and message in the MIDI file
        for i, track in enumerate(mf.tracks):
            print(f"Processing track {i + 1}/{len(mf.tracks)}")

            for msg in track:
                print(f"Message: {msg}")

                # Handle 'note_on' messages
                if msg.type == 'note_on' and msg.velocity > 0:
                    pitch = msg.note
                    duration = msg.time  # Duration in ticks

                    # Validate pitch
                    if 0 <= pitch <= 127:  # Ensure pitch is within MIDI range
                        # Ensure duration is within acceptable limits
                        if 0 <= duration <= 65535:  # Check if duration can be represented in 2 bytes
                            # Split duration into two bytes and store in the list
                            duration_bytes = [duration >> 8, duration & 0xFF]
                            note_data.extend(
                                [pitch] + duration_bytes)  # Append the pitch and duration bytes to the data list

                            # Check if we have reached the maximum number of notes
                            if len(note_data) // 3 >= max_notes:  # Each note consists of 3 bytes (pitch + duration)
                                break  # Exit the loop if max notes reached

            if len(note_data) // 3 >= max_notes:
                break  # Exit the outer loop if max notes reached

        # Send all accumulated note data in one go
        if note_data:
            print(f"Sending {len(note_data) // 3} notes in bulk to Arduino...")
            arduino.write(bytes(note_data))

            # Wait for acknowledgment (optional)
            ack = arduino.read_until(b"ACK")
            if ack == b"ACK":
                print("Arduino received all notes successfully.")
            else:
                print("No acknowledgment received from Arduino.")
        else:
            print("No note data found to send.")

        print("Closing connection.")
        arduino.close()

    except serial.SerialException as se:
        print(f"Serial communication error: {se}")
    except FileNotFoundError as fnfe:
        print(f"MIDI file not found: {fnfe}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if arduino.is_open:
            arduino.close()
        print("Serial connection closed.")


def send_midi_to_arduino(midi_file):
    try:
        # Initialize serial connection to Arduino
        print("Attempting to connect to Arduino...")
        arduino = serial.Serial('COM13', 9600, timeout=1)  # Ensure the correct port is used
        time.sleep(2)  # Allow time for Arduino to reset
        print("Connected to Arduino!")

        mf = MidiFile(midi_file)
        print(f"Loaded MIDI file: {midi_file}")

        for i, track in enumerate(mf.tracks):
            print(f"Processing track {i + 1}/{len(mf.tracks)}")

            for msg in track:
                print(f"Message: {msg}")

                # Handle 'note_on' messages
                if msg.type == 'note_on' and msg.velocity > 0:
                    pitch = msg.note
                    duration = msg.time  # Duration in ticks

                    print(f"Sending note {pitch} with duration {duration}")
                    try:
                        # Split duration into two bytes
                        duration_bytes = [duration >> 8, duration & 0xFF]
                        arduino.write(bytes([pitch] + duration_bytes))

                        # Wait for ACK from Arduino before continuing
                        while True:
                            ack = arduino.read()  # Read one byte
                            if ack == b'\x06':  # 0x06 is the ASCII code for ACK
                                print("ACK received, sending next note...")
                                break  # Exit the loop once ACK is received
                            else:
                                print("Waiting for ACK...")

                    except Exception as e:
                        print(f"Error sending note to Arduino: {e}")

                # Example case for handling a chord
                elif msg.type == 'chord':
                    chord_pitches = [note.note for note in msg.notes]
                    duration = msg.time

                    print(f"Sending chord {chord_pitches} with duration {duration}")
                    try:
                        chord_bytes = [pitch for pitch in chord_pitches]
                        duration_bytes = [duration >> 8, duration & 0xFF]
                        arduino.write(bytes(chord_bytes + duration_bytes))

                        # Wait for ACK from Arduino before continuing
                        while True:
                            ack = arduino.read()  # Read one byte
                            if ack == b'\x06':  # 0x06 is the ASCII code for ACK
                                print("ACK received, sending next note...")
                                break  # Exit the loop once ACK is received
                            else:
                                print("Waiting for ACK...")

                    except Exception as e:
                        print(f"Error sending chord to Arduino: {e}")

        print("MIDI file processed successfully. Closing connection.")
        arduino.close()

    except serial.SerialException as se:
        print(f"Serial communication error: {se}")
    except FileNotFoundError as fnfe:
        print(f"MIDI file not found: {fnfe}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if arduino.is_open:
            arduino.close()
        print("Serial connection closed.")


def send_midi_to_arduino_updated(midi_file):
    try:
        print("Attempting to connect to Arduino...")
        arduino = serial.Serial('COM13', 9600, timeout=1)  # Adjust port as necessary
        time.sleep(2)  # Allow time for Arduino to reset
        print("Connected to Arduino!")

        mf = MidiFile(midi_file)
        print(f"Loaded MIDI file: {midi_file}")

        ticks_per_beat = mf.ticks_per_beat
        tempo = 500000  # Default tempo in microseconds per beat (120 BPM)
        current_time = 0

        for i, track in enumerate(mf.tracks):
            print(f"Processing track {i + 1}/{len(mf.tracks)}")

            notes_to_send = []  # To store notes in a chord

            for msg in track:
                print(f"Message: {msg}")

                if msg.type == 'set_tempo':
                    tempo = msg.tempo

                # Convert ticks to milliseconds
                delta_time_ms = msg.time * (tempo / ticks_per_beat) / 1000.0
                current_time += delta_time_ms

                if msg.type == 'note_on' and msg.velocity > 0:
                    pitch = msg.note

                    # Increase the duration slightly to slow down servos
                    duration = int(delta_time_ms * 1.5)

                    # Set a minimum duration of 100ms to prevent rapid movement
                    if duration < 100:
                        duration = 100

                    notes_to_send.append((pitch, duration))

                # If there's a delay or an end of the track, send all collected notes as a chord
                if (msg.type == 'note_on' and msg.velocity == 0) or (len(notes_to_send) > 0 and msg.time > 0):
                    for pitch, duration in notes_to_send:
                        print(f"Sending note {pitch} with duration {duration}")
                        try:
                            duration_bytes = [duration >> 8, duration & 0xFF]
                            arduino.write(bytes([pitch] + duration_bytes))

                            # Add a small delay between sending notes to prevent servo overload
                            time.sleep(0.05)  # 50 ms delay between notes

                        except Exception as e:
                            print(f"Error sending note to Arduino: {e}")

                    # Retry mechanism for ACK
                    retries = 3
                    ack_received = False
                    while retries > 0:
                        start_time = time.time()
                        while time.time() - start_time < 2:  # 2-second timeout
                            ack = arduino.read()  # Read one byte
                            if ack == b'\x06':  # ACK received
                                print("ACK received, sending next notes...")
                                ack_received = True
                                break
                        if ack_received:
                            break
                        else:
                            retries -= 1
                            print(f"ACK timeout, retrying... ({3 - retries}/3)")

                    if retries == 0:
                        print("Failed to receive ACK after 3 retries, moving to next notes...")

                    notes_to_send.clear()  # Clear the notes buffer for the next chord or note

        print("MIDI file processed successfully. Closing connection.")
        arduino.close()

    except serial.SerialException as se:
        print(f"Serial communication error: {se}")
    except FileNotFoundError as fnfe:
        print(f"MIDI file not found: {fnfe}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if arduino.is_open:
            arduino.close()
        print("Serial connection closed.")


# Worker thread for processing
class WorkerThread(QThread):
    update_message = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, input_file, output_dir):
        super().__init__()
        self.input_file = input_file
        self.output_dir = output_dir
        self.arduino = serial.Serial("COM13", 9600, timeout=1)
        time.sleep(2)  # Wait for Arduino to reset

    def run(self):
        self.update_message.emit("Converting MP3 to MIDI...")
        midi_file = self.convert_mp3_to_midi(self.input_file, self.output_dir)
        self.progress.emit(50)  # Update progress

        self.update_message.emit("Fitting MIDI notes to octave range...")
        fitted_midi_file = self.fit_midi_to_octave_range(midi_file, os.path.join(self.output_dir, 'adjusted_music.mid'))
        self.progress.emit(100)  # Update progress

        self.update_message.emit("MIDI notes processed")
        # Here you can add the code to send MIDI to Arduino

        # Send MIDI to Arduino
        # Updated function with better timing
        # send_midi_to_arduino_updated(fitted_midi_file)
        self.send_midi_to_arduino_updated_timing(fitted_midi_file)

        # First original function for sending notes/chords
        # send_midi_to_arduino(fitted_midi_file)

        # Function for sending all notes/chord at once
        # send_midi_to_arduino_bulk(fitted_midi_file)

    @staticmethod
    def convert_mp3_to_midi(input_dir, output_dir):
        basic_pitch_model = Model(ICASSP_2022_MODEL_PATH)
        midi_filename = os.path.splitext(os.path.basename(input_dir))[0] + "_basic_pitch.mid"

        predict_and_save(
            audio_path_list=[input_dir],
            output_directory=output_dir,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            save_midi=True,
            save_model_outputs=True,
            sonify_midi=True,
            save_notes=True
        )
        return os.path.join(output_dir, midi_filename)

    @staticmethod
    def fit_midi_to_octave_range(midi_file, output_file, min_note='C4', max_note='C5', gap_duration=0.2,
                                 tempo_factor=2.5, duration_extension=0.5):
        score = converter.parse(midi_file)

        original_notes = transpose_to_octave(score, min_note, max_note)

        # Remove repeating chords
        unique_score = remove_repeating_chords(score)

        # Shift overlapping notes instead of cutting them off
        smooth_score = shift_overlapping_notes(unique_score)

        # Removing sharp notes
        remove_sharps(smooth_score)

        mf = midi.translate.music21ObjectToMidiFile(smooth_score)
        mf.open(output_file, 'wb')
        mf.write()
        mf.close()
        return output_file

    def send_midi_to_arduino_updated_timing(self, midi_file, min_note_duration=200):
        """
        Sends MIDI data to Arduino while following the original timing and slowing down the tempo as needed.
        :param midi_file: Path to the MIDI file
        :param min_note_duration: Minimum duration in milliseconds for any note, regardless of MIDI timing.
        """
        try:
            mf = MidiFile(midi_file)
            print(f"Loaded MIDI file: {midi_file}")

            ticks_per_beat = mf.ticks_per_beat
            tempo = 500000  # Default tempo in microseconds per beat (120 BPM)
            current_time = 0

            for i, track in enumerate(mf.tracks):
                print(f"Processing track {i + 1}/{len(mf.tracks)}")

                notes_to_send = []  # To store notes in a chord

                for msg in track:
                    print(f"Message: {msg}")

                    if msg.type == 'set_tempo':
                        tempo = msg.tempo

                    # Convert ticks to milliseconds and apply the tempo scaling
                    delta_time_ms = msg.time * (tempo / ticks_per_beat) / 1000.0
                    current_time += delta_time_ms

                    if msg.type == 'note_on' and msg.velocity > 0:
                        pitch = msg.note

                        # Adjust the duration using tempo scale and ensure a minimum duration
                        duration = max(int(delta_time_ms), min_note_duration)

                        notes_to_send.append((pitch, duration))

                    # If there's a delay or an end of the track, send all collected notes as a chord
                    if (msg.type == 'note_off' or msg.time > 0) and len(notes_to_send) > 0:
                        print(f"Sending chord with {len(notes_to_send)} notes")

                        # Send all notes in the chord
                        self.send_chord_to_arduino(notes_to_send)
                        notes_to_send.clear()  # Clear the notes buffer for the next chord

                        # Wait for the correct timing before sending the next chord/note
                        time.sleep(delta_time_ms / 1000.0)

            print("MIDI file processed successfully. Closing connection.")
            self.arduino.close()

        except serial.SerialException as se:
            print(f"Serial communication error: {se}")
        except FileNotFoundError as fnfe:
            print(f"MIDI file not found: {fnfe}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            atexit.register(close_arduino_connection)
            if self.arduino.is_open:
                self.arduino.close()
            print("Serial connection closed.")

    def send_chord_to_arduino(self, notes):
        """
        Sends a chord (multiple notes) to the Arduino. Each note is sent along with its duration.
        """
        try:
            for pitch, duration in notes:
                # Convert duration to 2 bytes
                duration_bytes = [duration >> 8, duration & 0xFF]
                # Send the pitch and duration bytes to Arduino
                self.arduino.write(bytes([pitch] + duration_bytes))
                print(f"Sent note {pitch} with duration {duration}")
                # Add a small delay to avoid overloading the Arduino with many notes at once
                time.sleep(0.05)  # 50 ms delay between notes

            # Retry mechanism for ACK
            retries = 3
            ack_received = False

            while retries > 0:
                start_time = time.time()
                while time.time() - start_time < 2:  # 2-second timeout
                    ack = self.arduino.read()  # Read one byte
                    if ack == b'\x06':  # ACK received
                        print("ACK received, chord played successfully.")
                        ack_received = True
                        break
                if ack_received:
                    break
                else:
                    retries -= 1
                    print(f"ACK timeout, retrying... ({3 - retries}/3)")

            if retries == 0:
                print("Failed to receive ACK after 3 retries, moving to next notes...")

        except Exception as e:
            print(f"Error sending chord to Arduino: {e}")

    def close_arduino_connection(self):
        if self.arduino:
            print("Closing Arduino connection safely.")
            self.arduino.close()

    def send_midi_to_arduino_batch(self, midi_file, batch_size=5, min_note_duration=200):
        """
        Sends MIDI data to Arduino in batches while preserving original timing, without modifying the tempo.
        Chords are handled by sending all notes with the same delta time together.
        :param midi_file: Path to the MIDI file.
        :param batch_size: Number of notes to send in one batch before waiting for ACK.
        :param min_note_duration: Minimum duration in milliseconds for any note.
        """
        try:
            mf = MidiFile(midi_file)
            print(f"Loaded MIDI file: {midi_file}")

            ticks_per_beat = mf.ticks_per_beat
            tempo = 500000  # Default tempo in microseconds per beat (120 BPM)
            current_time = 0
            notes_batch = []  # To store notes in a batch
            chord_notes = []  # To store chord notes

            for i, track in enumerate(mf.tracks):
                print(f"Processing track {i + 1}/{len(mf.tracks)}")

                for msg in track:
                    if msg.type == 'set_tempo':
                        tempo = msg.tempo

                    # Convert ticks to milliseconds using the original tempo
                    delta_time_ms = msg.time * (tempo / ticks_per_beat) / 1000.0
                    current_time += delta_time_ms

                    if msg.type == 'note_on' and msg.velocity > 0:
                        pitch = msg.note
                        duration = max(int(delta_time_ms), min_note_duration)

                        # If delta time is zero, it's part of a chord
                        if msg.time == 0:
                            chord_notes.append((pitch, duration))
                        else:
                            # Send any collected chord notes first
                            if chord_notes:
                                self.send_batch_to_arduino(chord_notes)  # Send chord together
                                chord_notes.clear()

                            # Now add the individual note
                            notes_batch.append((pitch, duration))

                            # If the batch is full, send it
                            if len(notes_batch) >= batch_size:
                                self.send_batch_to_arduino(notes_batch)
                                notes_batch.clear()

                            # Respect the original timing
                            time.sleep(delta_time_ms / 1000.0)

                # If there's a chord to send after the loop, send it
                if chord_notes:
                    self.send_batch_to_arduino(chord_notes)
                    chord_notes.clear()

            # Send any remaining notes in the batch
            if notes_batch:
                self.send_batch_to_arduino(notes_batch)

            print("MIDI file processed successfully. Closing connection.")
            self.arduino.close()

        except Exception as e:
            print(f"An error occurred: {e}")

    def send_batch_to_arduino(self, notes_batch):
        """
        Sends a batch of notes or chords to Arduino and waits for ACK after the batch is sent.
        :param notes_batch: List of notes to send in a batch or a chord.
        """
        try:
            for pitch, duration in notes_batch:
                duration_bytes = [duration >> 8, duration & 0xFF]
                self.arduino.write(bytes([pitch] + duration_bytes))
                print(f"Sent note {pitch} with duration {duration}")

            # Wait for ACK for the entire batch or chord
            self.wait_for_ack()

        except Exception as e:
            print(f"Error sending batch to Arduino: {e}")

    def wait_for_ack(self, timeout=2):
        """
        Waits for an ACK from Arduino with a timeout.
        :param timeout: Time in seconds to wait for the ACK.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            ack = self.arduino.read()
            if ack == b'\x06':  # ACK received
                print("ACK received.")
                return
        print("ACK not received within timeout.")


# Main application class
# noinspection PyUnresolvedReferences
class MP3ToMIDIApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MidiPlayer")
        self.resize(720, 480)
        self.setAcceptDrops(True)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)

        # Progress Bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.progress_bar)
        self.progress_bar.hide()

        # Labels and buttons
        self.input_label = QLabel("Drag & Drop MP3 File Here", self)
        self.input_label.setAlignment(Qt.AlignCenter)
        self.input_label.setStyleSheet(self.get_default_stylesheet())
        self.layout.addWidget(self.input_label)

        self.output_label = QLabel("Drag & Drop Output Directory Here", self)
        self.output_label.setAlignment(Qt.AlignCenter)
        self.output_label.setStyleSheet(self.get_default_stylesheet())
        self.layout.addWidget(self.output_label)

        self.select_input_btn = QPushButton('Select MP3 File', self)
        self.select_input_btn.clicked.connect(self.select_input_file)
        self.layout.addWidget(self.select_input_btn)

        self.select_output_btn = QPushButton('Select Output Directory', self)
        self.select_output_btn.clicked.connect(self.select_output_directory)
        self.layout.addWidget(self.select_output_btn)

        self.process_button = QPushButton('Convert and Send', self)
        self.process_button.clicked.connect(self.start_conversion)
        self.layout.addWidget(self.process_button)

        self.process_again_button = QPushButton('Process Again', self)
        self.process_again_button.clicked.connect(self.process_again)
        self.process_again_button.hide()  # Hide it initially
        self.layout.addWidget(self.process_again_button)

        self.input_file = None
        self.output_dir = None

    @staticmethod
    def get_default_stylesheet():
        return """
            QLabel {
                border: 2px dashed #aaa;
                padding: 20px;
                background-color: #f9f9f9;
                color: #555;
            }
        """

    @staticmethod
    def get_hover_stylesheet():
        return """
            QLabel {
                border: 2px dashed #555;
                padding: 20px;
                background-color: #e0f7fa;
                color: #000;
            }
        """

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
            self.input_label.setStyleSheet(self.get_hover_stylesheet())
            self.output_label.setStyleSheet(self.get_hover_stylesheet())
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if os.path.isfile(file_path) and file_path.lower().endswith('.mp3'):
                self.input_file = file_path
                self.input_label.setText(f"Selected MP3: {file_path}")
            elif os.path.isdir(file_path):
                self.output_dir = file_path
                self.output_label.setText(f"Output Directory: {file_path}")

        # Restore default appearance after drop
        self.input_label.setStyleSheet(self.get_default_stylesheet())
        self.output_label.setStyleSheet(self.get_default_stylesheet())

    def select_input_file(self):
        self.input_file, _ = QFileDialog.getOpenFileName(self, "Select MP3 File", "", "MP3 Files (*.mp3)")
        if self.input_file:
            self.input_label.setText(f"Selected MP3: {self.input_file}")

    def select_output_directory(self):
        self.output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if self.output_dir:
            self.output_label.setText(f"Output Directory: {self.output_dir}")

    def start_conversion(self):
        if not self.input_file or not self.output_dir:
            print("Please select both MP3 file and output directory.")
            return

        # Hide other UI elements
        self.progress_bar.show()
        self.input_label.hide()
        self.output_label.hide()
        self.select_input_btn.hide()
        self.select_output_btn.hide()
        self.process_button.hide()

        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self.worker = WorkerThread(self.input_file, self.output_dir)
        self.worker.update_message.connect(self.show_message)
        self.worker.progress.connect(self.update_progress)
        self.worker.start()

    def process_again(self):
        self.input_label.setText("Drag & Drop MP3 File Here")
        self.output_label.setText("Drag & Drop Output Directory Here")
        self.input_file = None
        self.output_dir = None

        # Show all original UI elements again
        self.input_label.show()
        self.output_label.show()
        self.select_input_btn.show()
        self.select_output_btn.show()
        self.process_button.show()
        self.progress_bar.hide()
        self.process_again_button.hide()  # Hide process again button

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        if value == 100:
            # Show all elements again after processing is done
            self.process_again_button.show()  # Show process again button

    def show_message(self, message):
        self.input_label.setText(message)
        self.input_label.repaint()  # Update the label immediately


# MIDI processing functions
def transpose_to_octave(score, min_note='C4', max_note='C5'):
    lower_pitch = note.Pitch(min_note)
    upper_pitch = note.Pitch(max_note)
    original_notes = []

    for element in score.flat.notesAndRests:
        if isinstance(element, note.Note):
            if element.pitch < lower_pitch:
                # Transpose up to the nearest note within the octave range
                transposition = 12  # One octave up
                element.pitch = element.pitch.transpose(transposition)
            elif element.pitch > upper_pitch:
                # Transpose down to the nearest note within the octave range
                transposition = -12  # One octave down
                element.pitch = element.pitch.transpose(transposition)
            else:
                original_notes.append(element)  # Keep original notes
        elif isinstance(element, chord.Chord):
            new_pitches = []
            for pitch in element.pitches:
                if pitch < lower_pitch:
                    pitch = pitch.transpose('P8')  # Transpose up
                elif pitch > upper_pitch:
                    pitch = pitch.transpose('-P8')  # Transpose down
                else:
                    original_notes.append(note.Note(pitch))  # Keep original notes
                new_pitches.append(pitch)  # Always add the transposed pitch
            element.pitches = new_pitches

    return original_notes


def remove_repeating_chords(score):
    """Remove consecutive repeating chords."""
    unique_chords = []
    prev_chord = None

    for element in score.flat.notesAndRests:
        if isinstance(element, chord.Chord):
            chord_pitches = sorted([p.midi for p in element.pitches])  # Use sorted MIDI values to compare
            if chord_pitches != prev_chord:
                unique_chords.append(element)
                prev_chord = chord_pitches
        else:
            unique_chords.append(element)

    return stream.Stream(unique_chords)


def remove_sharps(score):
    """Remove all sharp notes from the score."""
    notes_to_remove = []

    print("Identifying sharp notes to remove...")
    for element in score.flat.notesAndRests:
        if isinstance(element, note.Note):
            if '#' in element.nameWithOctave:
                notes_to_remove.append(element)
                print(f"Found sharp note: {element.nameWithOctave}")
        elif isinstance(element, chord.Chord):
            # Remove pitches from chord that are sharps
            new_pitches = [pitch for pitch in element.pitches if '#' not in pitch.nameWithOctave]
            if len(new_pitches) != len(element.pitches):
                chord_pitches = ', '.join(p.nameWithOctave for p in element.pitches)
                print(f"Chord {chord_pitches} had sharps and is being modified.")
            element.pitches = new_pitches

            # If no pitches remain in the chord, mark it for removal
            if not element.pitches:
                notes_to_remove.append(element)
                print(f"Chord {chord_pitches} has no remaining pitches and will be removed.")

    # Remove sharp notes from the score
    for note_to_remove in notes_to_remove:
        if isinstance(note_to_remove, note.Note):
            print(f"Removing note: {note_to_remove.nameWithOctave}")
        else:
            print(f"Removing chord with pitches: {', '.join(p.nameWithOctave for p in note_to_remove.pitches)}")

        if note_to_remove in score.flat.notesAndRests:
            score.remove(note_to_remove)
        else:
            print(f"Note or chord not found in score.")


def shift_overlapping_notes(score):
    """Shift overlapping notes instead of cutting them off."""
    for i in range(len(score.flat.notesAndRests) - 1):
        current_note = score.flat.notesAndRests[i]
        next_note = score.flat.notesAndRests[i + 1]

        if isinstance(current_note, (note.Note, chord.Chord)) and isinstance(next_note, (note.Note, chord.Chord)):
            # Calculate the end time of the current note
            current_end_time = current_note.offset + current_note.quarterLength

            # Check if the next note starts before the current note ends
            if next_note.offset < current_end_time:
                # Move the next note's start time to the current note's end time
                next_note.offset = current_end_time

    return score


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MP3ToMIDIApp()
    ex.show()
    sys.exit(app.exec_())
