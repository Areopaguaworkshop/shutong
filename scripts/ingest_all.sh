#!/bin/bash
set -e

CITEINDEX="${CITEINDEX_BIN:-citeindex}"
CORPUS_ROOT="${CORPUS_ROOT:-./corpus}"
DIR="${SOURCE_DIR:-./example}"
INGEST_TIMEOUT="${INGEST_TIMEOUT:-7200}"

# Files to ingest (skipping duplicates and the epub)
FILES=(
    "阿甲道教课论文2019daoismFinalPaperComment.pdf"
    "阿甲道教课程笔记.pdf"
    "阿甲课程笔记2019.pdf"
    "道教百科.PDF"
    "道教征略.pdf"
    "老子今注今译 参照简帛本最新修订版 (陈鼓应注译).pdf"
    "楚地出土戰國簡冊合集：郭店楚墓竹書 (武漢大學簡帛研究中心).pdf"
    "悟真篇-Pregodio-en.pdf"
    "庄子集释[清]郭庆藩（全四册） (庄子集释[清]郭庆藩（全四册）).pdf"
    "帛书老子校注（中华书局） (高明, 老子).pdf"
    "内丹2_kohn_modes_of_mutation.pdf"
    "Schipper-1993-Taoist-body.pdf"
    "Pregadio-Awakening to Reality The Regulated Verses of the Wuzhen Pian, a Taoist Classic of Internal Alchemy.pdf"
    "Pregadio2-2021-MAN-BIRD MOUNTAIN.pdf"
    "Pregadio-2024-Dictionary of Taoist Internal Alchemy.pdf"
    "Pregadio-2019-The Way of the Golden Elixir An Introduction to Taoist Alchemy, Third Edition.pdf"
    "Pregadio-2019-Taoist Internal Alchemy An Anthology of Neidan Texts.pdf"
    "Pregadio_2013_入药镜英译.pdf"
    "Pregadio-2013-The Encyclopedia of Taoism 2-Volume Set.pdf"
    "Pregadio-2006-Great Clarity Daoism and Alchemy in Early Medieval China.pdf"
    "Kohn-2008-道教导引.pdf"
    "Guo-qingfan-庄子集释 (郭庆藩).pdf"
    "Daoism-Handbook.pdf"
    "David对硕士论文的评价.pdf"
    "daoismS2019笔记.pdf"
    "Dao_Companion_to_neo_Confucian_philosophy_Springer2010_153_197.pdf"
    "Bokenkamp-Early Daoist Scriptures.pdf"
    "Pregadio-Foundations of Internal Alchemy The Taoist Practice of Neidan.docx"
    # Skipped duplicates:
    # "Daoism Handbook.pdf" -> duplicate of Daoism-Handbook.pdf (smaller)
    # "Pregadio-2024-Dictionary_of_Taoist_Internal_Alchemy.pdf" -> duplicate (1.4MB vs 250MB)
    # "Pregadio-2020-Man-Bird Mountain.pdf" -> duplicate of Pregadio2-2021 (smaller)
    # "early-Daoist-Scriptures-t.pdf" -> duplicate of Bokenkamp (smaller)
    # "Encyclopedia_of_Taoism.pdf" -> duplicate of Pregadio-2013 (subset)
    # "Pregadio_2009_悟真篇英译.pdf" -> likely duplicate of 悟真篇-Pregodio-en.pdf
    # "Pregadio-Foundations of Internal Alchemy The Taoist Practice of Neidan.epub" -> converted to docx
)

TOTAL=${#FILES[@]}
CURRENT=0
SUCCESS=0
FAILED=0
FAILED_FILES=()

for FILE in "${FILES[@]}"; do
    CURRENT=$((CURRENT + 1))
    FILEPATH="$DIR/$FILE"
    if [ ! -f "$FILEPATH" ]; then
        echo "[$CURRENT/$TOTAL] SKIP (not found): $FILE"
        FAILED=$((FAILED + 1))
        FAILED_FILES+=("$FILE (not found)")
        continue
    fi
    
    echo "============================================================"
    echo "[$CURRENT/$TOTAL] Ingesting: $FILE"
    echo "============================================================"
    
    if timeout "$INGEST_TIMEOUT" "$CITEINDEX" "$FILEPATH" --corpus-root "$CORPUS_ROOT" --page-range all 2>&1; then
        echo "[$CURRENT/$TOTAL] SUCCESS: $FILE"
        SUCCESS=$((SUCCESS + 1))
    else
        EXIT_CODE=$?
        echo "[$CURRENT/$TOTAL] FAILED (exit $EXIT_CODE): $FILE"
        FAILED=$((FAILED + 1))
        FAILED_FILES+=("$FILE (exit $EXIT_CODE)")
    fi
    echo ""
done

echo ""
echo "============================================================"
echo "INGESTION COMPLETE"
echo "============================================================"
echo "Total: $TOTAL"
echo "Success: $SUCCESS"
echo "Failed: $FAILED"
if [ ${#FAILED_FILES[@]} -gt 0 ]; then
    echo "Failed files:"
    for F in "${FAILED_FILES[@]}"; do
        echo "  - $F"
    done
fi
