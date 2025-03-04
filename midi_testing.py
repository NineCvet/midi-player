import sys
import os
import time
import serial
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QFileDialog
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict_and_save, Model
from music21 import converter, note, chord, midi, stream

# Arduino configuration
# arduino_port = 'COM3'
# baud_rate = 9600
#
# # Initializing Arduino connection
# arduino = serial.Serial(arduino_port, baud_rate)
time.sleep(2)  # Waiting for connection to establish

# atexit.register(lambda: arduino.close() if arduino.is_open else None)


# noinspection PyUnresolvedReferences
class MP3ToMIDIApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MidiPlayer")
        self.resize(720, 480)
        self.setAcceptDrops(True)

        # Set up central widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)

        # Labels for displaying paths
        self.input_label = QLabel("Drag & Drop MP3 File Here", self)
        self.input_label.setAlignment(Qt.AlignCenter)
        self.input_label.setStyleSheet(self.get_default_stylesheet())
        self.layout.addWidget(self.input_label)

        self.output_label = QLabel("Drag & Drop Output Directory Here", self)
        self.output_label.setAlignment(Qt.AlignCenter)
        self.output_label.setStyleSheet(self.get_default_stylesheet())
        self.layout.addWidget(self.output_label)

        # Buttons for selecting files and directories
        self.select_input_btn = QPushButton('Select MP3 File', self)
        self.select_input_btn.clicked.connect(self.select_input_file)
        self.layout.addWidget(self.select_input_btn)

        self.select_output_btn = QPushButton('Select Output Directory', self)
        self.select_output_btn.clicked.connect(self.select_output_directory)
        self.layout.addWidget(self.select_output_btn)

        # Button to process the files
        self.process_button = QPushButton('Convert and Send', self)
        self.process_button.clicked.connect(self.convert_and_send)
        self.layout.addWidget(self.process_button)

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

        # Restoring default appearance after drop
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

    def show_message(self, message):
        self.input_label.setText(message)
        self.input_label.repaint()  # Updating the label immediately

    def convert_and_send(self):
        if not self.input_file or not self.output_dir:
            print("Please select both MP3 file and output directory.")
            return

        self.show_message("Converting MP3 to MIDI...")
        # Converting MP3 to MIDI
        midi_file = self.convert_mp3_to_midi(self.input_file, self.output_dir)

        self.show_message("Fitting MIDI notes to octave range...")
        # Fitting MIDI notes to octave range and send to Arduino
        fitted_midi_file = self.fit_midi_to_octave_range(midi_file, os.path.join(self.output_dir, 'adjusted_music.mid'))

        self.midi_to_arduino(fitted_midi_file)
        self.show_message("MIDI notes processed")
        print("MIDI notes sent to Arduino")

    @staticmethod
    def convert_mp3_to_midi(input_dir, output_dir):
        basic_pitch_model = Model(ICASSP_2022_MODEL_PATH)
        # Generalizing the output MIDI file name based on the input filename
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
    def fit_midi_to_octave_range(midi_file, output_file, min_note='C4', max_note='C5', gap_duration=0.2, tempo_factor=2.5, duration_extension=0.5):
        # Loading the MIDI file
        score = converter.parse(midi_file)

        # Transposing to the specified octave range
        original_notes = transpose_to_octave(score, min_note, max_note)

        # Moving sharps up to their next natural note
        move_sharps_up(score)

        # Smooth the notes and add gaps
        smooth_score = smooth_notes_and_add_gaps(score, tempo_factor, duration_extension, gap_duration, original_notes)

        # Saving the transposed score to a new MIDI file
        mf = midi.translate.music21ObjectToMidiFile(smooth_score)
        mf.open(output_file, 'wb')
        mf.write()
        mf.close()
        return output_file

    def midi_to_arduino(self, midi_file):
        print("Sending to arduino!")
    #     score = converter.parse(midi_file)
    #     for element in score.flat.notes:
    #         if isinstance(element, note.Note):
    #             midi_note = element.midi
    #             arduino.write(bytes([midi_note]))  # Sending MIDI note as byte
    #             time.sleep(element.quarterLength)  # Simulating note duration
    #         arduino.write(b'0')  # Stop signal


# MIDI processing functions
def transpose_to_octave(score, min_note='C4', max_note='C5'):
    """Transpose notes and chords to fit within the specified octave range more efficiently."""
    lower_pitch = note.Pitch(min_note)
    upper_pitch = note.Pitch(max_note)
    original_notes = []

    for element in score.flat.notesAndRests:
        if isinstance(element, note.Note):
            if element.pitch < lower_pitch:
                element.pitch = element.pitch.transpose(12)  # One octave up
            elif element.pitch > upper_pitch:
                element.pitch = element.pitch.transpose(-12)  # One octave down
            else:
                original_notes.append(element)
        elif isinstance(element, chord.Chord):
            new_pitches = []
            for pitch in element.pitches:
                if pitch < lower_pitch:
                    pitch = pitch.transpose(12)
                elif pitch > upper_pitch:
                    pitch = pitch.transpose(-12)
                new_pitches.append(pitch)
            element.pitches = new_pitches

    return original_notes


def move_sharps_up(score):
    """Move sharp notes up to their next natural counterpart."""
    for element in score.flat.notesAndRests:
        if isinstance(element, note.Note) and '#' in element.nameWithOctave:
            new_pitch = element.pitch.transpose(1)
            element.pitch = new_pitch
        elif isinstance(element, chord.Chord):
            new_pitches = []
            for pitch in element.pitches:
                if '#' in pitch.nameWithOctave:
                    new_pitch = pitch.transpose(1)
                    new_pitches.append(new_pitch)
                else:
                    new_pitches.append(pitch)
            element.pitches = new_pitches


def smooth_notes_and_add_gaps(score, tempo_factor, duration_extension, gap_duration, original_notes):
    """Adjust note durations and offsets to avoid overlaps and ensure smooth flow."""
    active_notes = {}
    modified_elements = []

    for element in score.flat.notesAndRests:
        if isinstance(element, (note.Note, chord.Chord)):
            start_time = element.offset
            duration = (element.quarterLength / tempo_factor) + duration_extension
            end_time = start_time + duration

            if isinstance(element, note.Note):
                pitch = element.pitch.midi

                if pitch in active_notes:
                    last_end_time, last_duration = active_notes[pitch]
                    if last_end_time > start_time:
                        if last_end_time + gap_duration <= end_time:
                            element.offset = last_end_time + gap_duration
                            start_time = element.offset
                            end_time = start_time + duration

                active_notes[pitch] = (end_time, duration)
                element.quarterLength = duration
                modified_elements.append(element)

            elif isinstance(element, chord.Chord):
                new_pitches = []
                for pitch in element.pitches:
                    midi_pitch = pitch.midi
                    if midi_pitch not in active_notes or active_notes[midi_pitch][0] <= start_time:
                        new_pitches.append(pitch)
                        active_notes[midi_pitch] = (end_time, duration)

                element.pitches = new_pitches
                element.quarterLength = duration
                modified_elements.append(element)

    new_stream = stream.Stream()
    for element in modified_elements:
        new_stream.append(element)
    return new_stream


if __name__ == '__main__':
    # try:
        app = QApplication(sys.argv)
        ex = MP3ToMIDIApp()
        ex.show()
        sys.exit(app.exec_())
    # finally:
        # if arduino.is_open:
        #     arduino.close()
