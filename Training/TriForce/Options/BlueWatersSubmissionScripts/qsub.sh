hl=(1 2 3 4 5)
ne=(256 512 1024 2048 4096)
lr=(0.0001 0.0005 0.001)
dp=(0.05 0.1 0.15 0.2 0.25)
#ws=(11 21 31 41 51)

for hl_i in ${hl[@]}
do
    cp qsub_template.in qsub.in
    for ne_i in ${ne[@]}
    do
        sed 's/JOBNAME/'${hl_i}'/g' -i qsub.in
        for lr_i in ${lr[@]}
        do
            for dp_i in ${dp[@]}
            do
                echo "aprun -n 1 python3 triforce.py Output_${hl_i}_${ne_i}_${lr_i}_${dp_i} ${hl_i} ${ne_i} ${lr_i} ${dp_i} > Output/Output_${hl_i}_${ne_i}_${lr_i}_${dp_i}_log.txt &" >> qsub.in
            done
        done
    done
    echo "wait" >> qsub.in
    qsub qsub.in
done
