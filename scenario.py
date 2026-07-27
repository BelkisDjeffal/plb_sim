SCENARIO = {
    "name": "no_fault_3_classes",
    "seed": 42,
    "repetitions": 1,

    "platform": {
        "replicas": 8,
        "slots_per_replica": 100,
        "replica_names": [],
        "replica_speed": "1Gf",
        "replica_core": 1,
        "network_bandwidth": "100Gbps",
        "network_latency": "1us",
    },

    "workload": {
        "duration_s": 180,
        "total_workers": 600,
        "classes": ["enterprise", "premium", "freemium"],
        "class_counts": [200, 200, 200],
        "arrival_model": "poisson",
        "lifetime": {
            "type": "uniform",
            "min_s": 10,
            "max_s": 30,
        },
        "profile_type": "delay",
    },

    "scheduler_config": {
        "class_order": ["enterprise", "premium", "freemium"],
        "theta": 10,
        "alpha": 0.7,
        "kappa": {
            "enterprise": 1,
            "premium": 1,
            "freemium": 1,
        },
        "targets": {
            "enterprise": 2,
            "premium": 2,
            "freemium": 2,
        },
        "initial_pools": {
            "enterprise": [0, 1],
            "premium": [2, 3],
            "freemium": [4, 5],
            "mixed": [6, 7],
        },
        "donor_policy": "load_first",
        "higher_borrow_mode": "safe_surplus",
        "return_policy": "simple",
    },

    "schedulers": ["round_robin", "least_loaded", "plb_nclass"],

    "faults": {
        "enabled": False,
        "events": [],
    },
}
