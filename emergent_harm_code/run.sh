python -u run_experiment.py --experiment reputation --model-mix "default=openai:gpt-4o-mini" --ticks 10 --log-level INFO --report 2>&1 | tee ./logs/reputation_Mgpt-4o-mini_T10.log
python -u run_experiment.py --experiment reputation --model-mix "default=openai:gpt-4o-mini" --ticks 50 --log-level INFO --report 2>&1 | tee ./logs/reputation_Mgpt-4o-mini_T50.log

python -u run_experiment.py --experiment consensus --model-mix "default=openai:gpt-4o-mini" --ticks 10 --log-level INFO --report 2>&1 | tee ./logs/consensus_Mgpt-4o-mini_T10_run1.log
python -u run_experiment.py --experiment consensus --model-mix "default=openai:gpt-4o-mini" --ticks 10 --log-level INFO --report 2>&1 | tee ./logs/consensus_Mgpt-4o-mini_T10_run2.log
python -u run_experiment.py --experiment consensus --model-mix "default=openai:gpt-4o-mini" --ticks 10 --log-level INFO --report 2>&1 | tee ./logs/consensus_Mgpt-4o-mini_T10_run3.log

python -u run_experiment.py --experiment proxy_chain --model-mix "default=openai:gpt-4o-mini" --ticks 10 --log-level INFO --report 2>&1 | tee ./logs/proxy_chain_Mgpt-4o-mini_T10.log