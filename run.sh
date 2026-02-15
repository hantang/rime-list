#!/usr/bin/env bash
set -eu
batch="${1:-100}"

readme_file="README.md"
data_file="data.tsv"
repo_file="repo_data.json"

# readm update: macos: ggrep
last_update=$(grep -oP '(?<=<!-- START-DATE -->\*)[0-9-]+(?=\*<!-- END-DATE -->)' $readme_file)
today=$(date +%Y-%m-%d)

if [ "$last_update" == "$today" ]; then
    echo "Ignore update. Readme updated at: $last_update"
    exit 0
fi

# echo "Inistall deps"
# pip install -r requirements.txt >/dev/null 2>&1

echo "Update data"
python src/run-stats.py -f $data_file -o $repo_file -b $batch

echo "Update readme"
python src/run-doc.py -f $data_file -d $repo_file -o $readme_file

echo Done
