from datetime import time
import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QProgressBar,
)
from PyQt5.QtCore import pyqtSignal, QObject
import shutil
import random

from matplotlib.axes import Axes
from rich.console import Console

from LLAMOSC.agents.contributor import ContributorAgent
from LLAMOSC.agents.maintainer import MaintainerAgent
from LLAMOSC.agents.issue_creator import IssueCreatorAgent
from LLAMOSC.simulation.issue import Issue
from LLAMOSC.simulation.sim import Simulation

from LLAMOSC.utils import (
    repo_commit_current_changes,
    repo_apply_diff_and_commit,
    query_ollama,
    run_command,
    stop_running_containers,
)
import argparse
import matplotlib.pyplot as plt
import matplotlib.animation as animation


class WorkerSignals(QObject):
    update_log = pyqtSignal(str)


class SimulationApp(QWidget):
    def __init__(self):
        super().__init__()

        self.initUI()

    def initUI(self):
        self.setWindowTitle("LLAMOSC Simulation")

        layout = QVBoxLayout()

        # Contributors input
        layout.addWidget(QLabel("Number of Contributors:"))
        self.contributors_input = QLineEdit()
        self.contributors_input.setText("5")  # Default value
        layout.addWidget(self.contributors_input)

        # Maintainers input
        layout.addWidget(QLabel("Number of Maintainers:"))
        self.maintainers_input = QLineEdit()
        self.maintainers_input.setText("3")  # Default value
        layout.addWidget(self.maintainers_input)

        # Issues input
        layout.addWidget(QLabel("Number of Issues:"))
        self.issues_input = QLineEdit()
        self.issues_input.setText("5")  # Default value
        layout.addWidget(self.issues_input)

        # Use ACR checkbox
        self.acr_checkbox = QCheckBox("Use ACR")
        layout.addWidget(self.acr_checkbox)

        # Algorithm selection
        layout.addWidget(QLabel("Decision Making Algorithm:"))
        self.algorithm_selection = QComboBox()
        self.algorithm_selection.addItems(["a (Authoritarian)", "d (Decentralized)"])
        layout.addWidget(self.algorithm_selection)

        # Issue path selection
        layout.addWidget(QLabel("Select Issues Path:"))
        self.issues_path_button = QPushButton("Select Path")
        self.issues_path_button.clicked.connect(self.select_issues_path)
        layout.addWidget(self.issues_path_button)
        self.issues_path_label = QLabel("No path selected")
        layout.addWidget(self.issues_path_label)

        # Start simulation button
        self.start_button = QPushButton("Start Simulation")
        layout.addWidget(self.start_button)
        self.start_button.clicked.connect(self.start_simulation)

        # Log output
        self.log_output = QLabel("Logs will be displayed here.")
        layout.addWidget(self.log_output)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Adjust layout stretch factors
        layout.setStretchFactor(self.contributors_input, 1)
        layout.setStretchFactor(self.maintainers_input, 1)
        layout.setStretchFactor(self.issues_input, 1)
        layout.setStretchFactor(self.acr_checkbox, 0)
        layout.setStretchFactor(self.algorithm_selection, 1)
        layout.setStretchFactor(self.issues_path_button, 0)
        layout.setStretchFactor(self.issues_path_label, 1)
        layout.setStretchFactor(self.start_button, 0)
        layout.setStretchFactor(self.log_output, 1)
        layout.setStretchFactor(self.progress_bar, 0)

        # Set minimum size to ensure widgets are properly visible
        self.setMinimumSize(400, 300)

        # Set layout and show window
        self.setLayout(layout)
        self.show()

    def select_issues_path(self):
        issues_path = QFileDialog.getExistingDirectory(self, "Select Issues Directory")
        if issues_path:
            self.issues_path_label.setText(issues_path)
            self.issues_path = issues_path

    def init_plot(axis: Axes, x_label, y_label, x_max, y_max, title, lines):
        axis.set_xlim(0, x_max + 1)
        axis.set_ylim(0, y_max + 1)
        axis.set_xlabel(x_label)
        axis.set_ylabel(y_label)
        axis.set_title(title)
        axis.legend()

    def update_log_output(self, message):
        current_text = self.log_output.text()
        new_text = current_text + "\n" + message
        self.log_output.setText(new_text)

    def update_progress_bar(self, current, total):
        progress = int((current / total) * 100)
        self.progress_bar.setValue(progress)

    def start_simulation(self):
        # Retrieve values from UI
        n_contributors = int(self.contributors_input.text())
        n_maintainers = int(self.maintainers_input.text())
        n_issues = int(self.issues_input.text())
        use_acr = self.acr_checkbox.isChecked()
        algorithm = self.algorithm_selection.currentText()[0]

        current_folder = os.path.dirname(os.path.abspath(__file__))
        project_dir = getattr(self, "issues_path", None)
        if not project_dir:  # If the user didn't select a path, use the default.
            project_dir = os.path.join(
                current_folder, "..", "..", "..", "..", "calculator_project"
            )

        # testing
        other = os.path.join(
            current_folder, "..", "..", "..", "..", "calculator_project"
        )
        self.progress_bar.setValue(0)
        self.log_output.setText(
            "Starting simulation with the following parameters:\n"
            f"Contributors: {n_contributors}\n"
            f"Maintainers: {n_maintainers}\n"
            f"Issues: {n_issues}\n"
            f"Use ACR: {use_acr}\n"
            f"Algorithm: {algorithm}\n"
            f"Issues Path: {project_dir}"
        )

        self.progress_bar.setValue(100)

        console = Console()

        def log_and_print(message):
            # special function to log and print messages in UI directly
            console.print(message)
            self.log_output.setText(message)

        # Clear the project directory
        repo_commit_current_changes(project_dir)

        # Get the path to the issues folder
        # current folder
        issues_parent_folder = os.path.join(project_dir, "issues")
        issues_folder = os.path.join(issues_parent_folder, "pending")
        # Loop through all the files in the issues folder
        self.progress_bar.setValue(0)
        # log_and_print("Reading existing issues from the issues folder...")
        issues = []
        total_files = len(os.listdir(issues_folder))
        index = 0
        for index, filename in enumerate(os.listdir(issues_folder)):
            # Create the file path
            file_path = os.path.join(issues_folder, filename)

            # Extract the issue id from the filename
            issue_id = int(filename.split("_")[1].split(".")[0])

            # Create the issue object
            # TODO: Better way to get issue difficulty
            issue = Issue(issue_id, (issue_id + 1) % 5, file_path)

            # Add the issue to the issues list
            issues.append(issue)

            # Update progress
            self.update_progress_bar(index + 1, total_files)

        if len(issues) < n_issues:
            self.progress_bar.setValue(0)
            log_and_print("IssueCreatorAgent creating new issues...")

            issue_creator = IssueCreatorAgent(name="Issue Creator")
            existing_code = """"""

            for root, _, files in os.walk(project_dir):
                for file in files:
                    if file.endswith(".py"):
                        with open(os.path.join(root, file), "r") as code_file:
                            existing_code += code_file.read() + "\n"

            # create the required number of issues
            for i in range(len(issues) + 1, n_issues + 1):
                issue = issue_creator.create_issue(issues, existing_code, issues_folder)
                issues.append(issue)
                # Update progress
                self.update_progress_bar(
                    i - total_files + 1, n_issues - total_files + 1
                )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = SimulationApp()
    sys.exit(app.exec_())
