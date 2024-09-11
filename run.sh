#!/usr/bin/env bash
set -eu

readme_file="README.md"
data_file="data.tsv"
temp_dir="temp"

# readm update: macos: ggrep
last_update=$(grep -oP '(?<=<!-- START-DATE -->\*)[0-9-]+(?=\*<!-- END-DATE -->)' $readme_file)
today=$(date +%Y-%m-%d)

if [ "$last_update" == "$today" ]; then
    echo "Ignore update. Readme updated at: $last_update"
    exit 0
fi

echo "Inistall deps"
pip install -r requirements.txt >/dev/null 2>&1

echo "Update data"
retry=2
for ((i = 0; i < $retry; i++)); do
    python src/run-crawl.py -f $data_file -t $temp_dir -g $TOKEN
done

echo "Update readme"
python src/run-doc.py -f $data_file -t $temp_dir -o $readme_file

echo Done
