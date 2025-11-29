import os
import hashlib
import json
import time
from datetime import datetime


class FileInfo:
    def __init__(self, filepath, relative_path):
        self.relative_path = relative_path
        stats = os.stat(filepath)
        self.info = {
            'hash': self._calculate_hash(filepath),
            'size': stats.st_size,
            'modified_time': stats.st_mtime,
            'creation_time': stats.st_ctime,
            'path': relative_path,
            'inode': self._get_file_id(stats)  # unix unique inode id
        }

    def _get_file_id(self, stats):  # Get unique identifier (Inode for Unix - FileID for Windows).
        try:  # try for Inode number of unix
            return f"{stats.st_dev}:{stats.st_ino}"
        except AttributeError:  # fallback to file index for windows
            try:
                return f"{stats.st_dev}:{stats.st_file_index}"
            except AttributeError:
                # no unique id if neither unix nor windows
                return None

    def _calculate_hash(self, filepath):  # Calculate the sha256 hash
        sha256 = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:  # use binary mode for consistency
                while chunk := f.read(4096):  # 4kb chunks for large file handling
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            print(f"Error hashing file {filepath}: {e}")
            return None


def create_baseline(directory):  # json baseline creation with metadate for the files
    try:
        directory = os.path.abspath(directory)
        if not os.path.exists(directory):
            print(f"Error: Directory does not exist: {directory}")
            return

        baseline = {}
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename == '.baseline.json':
                    continue
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, directory)
                file_info = FileInfo(filepath, rel_path)  # file information object creation
                baseline[rel_path] = file_info.info

        baseline_path = os.path.join(directory, '.baseline.json')
        with open(baseline_path, 'w') as f:
            json.dump(baseline, f, indent=2)
        print(f"Baseline created with {len(baseline)} files at {baseline_path}")

    except Exception as e:
        print(f"Error creating baseline: {e}")


def check_changes(directory):  # check for any file changes in the dir
    try:
        directory = os.path.abspath(directory)
        baseline_path = os.path.join(directory, '.baseline.json')

        if not os.path.exists(baseline_path):
            print(f"No baseline found at {baseline_path}")
            print("Create one first with: python file_monitor.py create <directory>")
            return None, None, None, None, None

        with open(baseline_path, 'r') as f:
            baseline = json.load(f)

        new_files = []
        modified_files = []
        moved_files = []
        copied_files = []  # Track copied files extra
        deleted_files = []
        current_files = set()

        # Track content and inodes
        content_to_paths = {}  # Map content hashes to file paths
        inode_to_paths = {}  # Map inodes to file paths

        # (1) First pass: build maps and check for new or modified files
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename == '.baseline.json':
                    continue

                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, directory)
                current_files.add(rel_path)

                file_info = FileInfo(filepath, rel_path)
                current_hash = file_info.info['hash']
                current_inode = file_info.info['inode']

                if current_hash:
                    content_to_paths.setdefault(current_hash, []).append(rel_path)
                if current_inode:
                    inode_to_paths.setdefault(current_inode, []).append(rel_path)

                if rel_path not in baseline:  # Check if the file's a copy
                    is_copy = False
                    if current_hash:
                        for base_path, base_info in baseline.items():
                            if (base_info['hash'] == current_hash and
                                    base_info['inode'] != current_inode):
                                copied_files.append((base_path, rel_path))
                                is_copy = True
                                break
                    if not is_copy:
                        new_files.append(rel_path)
                else:  # Check if file was modified
                    baseline_info = baseline[rel_path]
                    if (current_hash != baseline_info['hash'] or
                            file_info.info['size'] != baseline_info['size'] or
                            abs(file_info.info['modified_time'] - baseline_info['modified_time']) > 1):
                        modified_files.append(rel_path)

        # (2) Second pass: check for any moved or deleted files
        for baseline_path, baseline_info in baseline.items():
            if baseline_path not in current_files:
                baseline_hash = baseline_info['hash']
                baseline_inode = baseline_info['inode']

                if baseline_inode and baseline_inode in inode_to_paths:  # File was moved - the inode exists elsewhere
                    for new_location in inode_to_paths[baseline_inode]:
                        if new_location not in new_files:
                            moved_files.append((baseline_path, new_location))
                elif baseline_hash in content_to_paths:
                    # Content exists elsewhere but different inode - might be a copy
                    # (This case is now handled in the first pass more effectively)
                    pass
                else:  # file is deleted
                    deleted_files.append(baseline_path)

        return new_files, modified_files, moved_files, copied_files, deleted_files

    except Exception as e:
        print(f"Error checking changes: {e}")
        return None, None, None, None, None


def monitor_directory(directory, interval=60):  # Monitor directory for all types of changes constantly
    try:
        directory = os.path.abspath(directory)
        print(f"Monitoring {directory}")
        print("Press Ctrl+C to stop...")

        while True:
            new, modified, moved, copied, deleted = check_changes(directory)
            if new is not None and any([new, modified, moved, copied, deleted]):
                print(f"\nChanges detected at {datetime.now()}")
                if new:
                    print("\nNew files:")
                    for f in new:
                        print(f"  + {f}")
                if modified:
                    print("\nModified files:")
                    for f in modified:
                        print(f"  ~ {f}")
                if moved:
                    print("\nMoved files:")
                    for old, new in moved:
                        print(f"  > {old} -> {new}")
                if copied:
                    print("\nCopied files:")
                    for orig, copy in copied:
                        print(f"  c {orig} -> {copy}")
                if deleted:
                    print("\nDeleted files:")
                    for f in deleted:
                        print(f"  - {f}")
            time.sleep(interval)

    except KeyboardInterrupt:  # Check if ctrl+c was pressed
        print("\nMonitoring stopped")
    except Exception as e:
        print(f"Error monitoring directory: {e}")


def main():
    import sys

    if len(sys.argv) < 3:
        print("Usage:")
        print("  Create baseline:  python file_monitor.py create <directory>")
        print("  Check once:      python file_monitor.py check <directory>")
        print("  Monitor:         python file_monitor.py monitor <directory> [interval_seconds]")
        return

    command = sys.argv[1]
    directory = os.path.abspath(sys.argv[2])

    if command == 'create':
        create_baseline(directory)
    elif command == 'check':
        new, modified, moved, copied, deleted = check_changes(directory)
        if new is not None:
            if not any([new, modified, moved, copied, deleted]):
                print("No changes detected")
            else:
                if new:
                    print("\nNew files:")
                    for f in new:
                        print(f"  + {f}")
                if modified:
                    print("\nModified files:")
                    for f in modified:
                        print(f"  ~ {f}")
                if moved:
                    print("\nMoved files:")
                    for old, new in moved:
                        print(f"  > {old} -> {new}")
                if copied:
                    print("\nCopied files:")
                    for orig, copy in copied:
                        print(f"  c {orig} -> {copy}")
                if deleted:
                    print("\nDeleted files:")
                    for f in deleted:
                        print(f"  - {f}")
    elif command == 'monitor':
        interval = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        monitor_directory(directory, interval)
    else:
        print("Unknown command. Use 'create', 'check', or 'monitor'")


if __name__ == "__main__":
    main()