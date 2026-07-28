import logging
import os
import time
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.db.cost_models import AccountMaster, ImportHistory, MonthlyCost, ServiceCost
from app.etl.account_loader import load_accounts
from app.etl.billing_loader import filter_and_log_months, get_billing_csv_files, process_billing_csv

logger = logging.getLogger(__name__)


def verify_database_integrity(session: Session) -> None:
    logger.info("Starting automatic database integrity verification...")

    # 1-4. Verify counts
    accounts_count = session.query(AccountMaster).count()
    service_costs_count = session.query(ServiceCost).count()
    monthly_costs_count = session.query(MonthlyCost).count()
    import_history_count = session.query(ImportHistory).count()

    logger.info(f"SELECT COUNT(*) FROM account_master; -> {accounts_count}")
    logger.info(f"SELECT COUNT(*) FROM service_costs; -> {service_costs_count}")
    logger.info(f"SELECT COUNT(*) FROM monthly_costs; -> {monthly_costs_count}")
    logger.info(f"SELECT COUNT(*) FROM import_history; -> {import_history_count}")

    # 5. Verify Root account does not exist
    root_in_master = session.query(AccountMaster).filter(
        (AccountMaster.account_id == "989469418905") | 
        (AccountMaster.team == "Root") | 
        (AccountMaster.environment == "Root")
    ).count()
    root_in_costs = session.query(ServiceCost).filter(
        (ServiceCost.account_id == "989469418905") | 
        (ServiceCost.team == "Root") | 
        (ServiceCost.environment == "Root")
    ).count()
    if root_in_master > 0 or root_in_costs > 0:
        logger.error(f"INTEGRITY FAILURE: Root account records found! Master={root_in_master}, Costs={root_in_costs}")
    else:
        logger.info("VERIFICATION: Root account check passed (0 records found).")

    # 6. Verify only SafeStart and AccuTrain exist in Product
    master_products = {p[0] for p in session.query(AccountMaster.product).distinct() if p[0]}
    costs_products = {p[0] for p in session.query(ServiceCost.product).distinct() if p[0]}
    invalid_master_p = master_products - {"SafeStart", "AccuTrain"}
    invalid_costs_p = costs_products - {"SafeStart", "AccuTrain"}
    if invalid_master_p or invalid_costs_p:
        logger.error(f"INTEGRITY FAILURE: Invalid Product values found! Master={invalid_master_p}, Costs={invalid_costs_p}")
    else:
        logger.info("VERIFICATION: Product values check passed.")

    # 7. Verify Team values
    valid_teams = {"QA", "Production", "UAT", "Development", "Developers", "Audit", "Logs", "Data Platform"}
    master_teams = {t[0] for t in session.query(AccountMaster.team).distinct() if t[0]}
    costs_teams = {t[0] for t in session.query(ServiceCost.team).distinct() if t[0]}
    invalid_master_t = master_teams - valid_teams
    invalid_costs_t = costs_teams - valid_teams
    if invalid_master_t or invalid_costs_t:
        logger.error(f"INTEGRITY FAILURE: Invalid Team values found! Master={invalid_master_t}, Costs={invalid_costs_t}")
    else:
        logger.info("VERIFICATION: Team values check passed.")

    # 8. Verify Environment values
    valid_envs = {"QA", "Production", "UAT", "Development", "Sandbox", "Audit", "Logs", "Data Platform"}
    master_envs = {e[0] for e in session.query(AccountMaster.environment).distinct() if e[0]}
    costs_envs = {e[0] for e in session.query(ServiceCost.environment).distinct() if e[0]}
    invalid_master_env = master_envs - valid_envs
    invalid_costs_env = costs_envs - valid_envs
    if invalid_master_env or invalid_costs_env:
        logger.error(f"INTEGRITY FAILURE: Invalid Environment values found! Master={invalid_master_env}, Costs={invalid_costs_env}")
    else:
        logger.info("VERIFICATION: Environment values check passed.")

    # 9. Verify developer_type contains only: Employee, Trainee, NULL
    valid_types = {"Employee", "Trainee"}
    master_types = {dt[0] for dt in session.query(AccountMaster.developer_type).distinct() if dt[0]}
    costs_types = {dt[0] for dt in session.query(ServiceCost.developer_type).distinct() if dt[0]}
    invalid_master_dt = master_types - valid_types
    invalid_costs_dt = costs_types - valid_types
    if invalid_master_dt or invalid_costs_dt:
        logger.error(f"INTEGRITY FAILURE: Invalid Developer Type values found! Master={invalid_master_dt}, Costs={invalid_costs_dt}")
    else:
        logger.info("VERIFICATION: Developer Type values check passed.")

    # 10. Verify billing_period values exclude current month
    current_month = datetime.utcnow().strftime("%Y-%m")
    m_periods = {p[0] for p in session.query(MonthlyCost.billing_period).distinct()}
    s_periods = {p[0] for p in session.query(ServiceCost.billing_period).distinct()}
    if current_month in m_periods or current_month in s_periods:
        logger.error(f"INTEGRITY FAILURE: Current month '{current_month}' found in database!")
    else:
        logger.info(f"VERIFICATION: Billing period values check passed (excludes '{current_month}').")


def run_etl_pipeline(session: Session) -> Dict[str, Any]:
    """Orchestrate and execute S3 to PostgreSQL ETL pipeline."""
    pipeline_start = time.time()
    logger.info("ETL Pipeline started.")

    summary = {
        "accounts_loaded": 0,
        "billing_files_processed": 0,
        "total_imported": 0,
        "total_updated": 0,
        "duplicates": 0,
        "root_skipped": 0,
        "unknown_accounts": 0,
        "monthly_summaries_created": 0,
        "execution_time": 0.0,
    }

    try:
        # 1. Load accounts
        logger.info("ETL Step: Reading Account.csv")
        accounts_map = load_accounts(session)
        summary["accounts_loaded"] = len(accounts_map)
        logger.info("Developer classification complete.")

        # 2. Get billing files
        all_billing_files = get_billing_csv_files()
        active_billing_files = filter_and_log_months(all_billing_files)

        # 3. Process each billing file
        for month, key in active_billing_files:
            file_start_time = time.time()
            started_at = datetime.utcnow()
            filename = os.path.basename(key)
            
            logger.info(f"ETL Step: Reading billing CSV {filename}")
            file_stats = process_billing_csv(session, key, month, accounts_map)
            
            file_end_time = time.time()
            completed_at = datetime.utcnow()
            file_execution_time = round(file_end_time - file_start_time, 2)

            status = "success" if file_stats["status"] == "success" else "failed"

            # Create entry in import_history
            import_record = ImportHistory(
                file_name=filename,
                billing_period=month,
                rows_read=file_stats["rows_read"],
                rows_inserted=file_stats["rows_imported"],
                rows_updated=file_stats["rows_updated"],
                duplicates=file_stats["duplicates"],
                started_at=started_at,
                completed_at=completed_at,
                status=status
            )
            session.add(import_record)
            session.commit()

            # Increment summaries
            if file_stats["status"] == "success":
                summary["billing_files_processed"] += 1
                summary["total_imported"] += file_stats["rows_imported"]
                summary["total_updated"] += file_stats["rows_updated"]
                summary["duplicates"] += file_stats["duplicates"]
                summary["root_skipped"] += file_stats["root_skipped"]
                summary["unknown_accounts"] += file_stats["unknown_accounts"]
                summary["monthly_summaries_created"] += 1

            # Print single file summary
            logger.info(
                f"\n--- Billing File Summary: {filename} ---\n"
                f"Billing Month: {month}\n"
                f"Rows Read: {file_stats['rows_read']}\n"
                f"Rows Imported: {file_stats['rows_imported']}\n"
                f"Rows Updated: {file_stats['rows_updated']}\n"
                f"Duplicates: {file_stats['duplicates']}\n"
                f"Root Skipped: {file_stats['root_skipped']}\n"
                f"Unknown Accounts: {file_stats['unknown_accounts']}\n"
                f"Execution Time: {file_execution_time} seconds\n"
                f"----------------------------------------"
            )

        pipeline_end = time.time()
        summary["execution_time"] = round(pipeline_end - pipeline_start, 2)

        # Print pipeline completion summary block exactly as requested
        logger.info(
            f"\n=== Pipeline Completion Summary ===\n"
            f"Accounts imported: {summary['accounts_loaded']}\n"
            f"Billing files imported: {summary['billing_files_processed']}\n"
            f"Service records imported: {summary['total_imported']}\n"
            f"Monthly summaries generated: {summary['monthly_summaries_created']}\n"
            f"Root accounts ignored: {summary['root_skipped']}\n"
            f"Unknown accounts skipped: {summary['unknown_accounts']}\n"
            f"Duplicate records prevented: {summary['duplicates']}\n"
            f"Total execution time: {summary['execution_time']} seconds\n"
            f"==================================="
        )

        # Run automatic post-ETL database verification
        verify_database_integrity(session)

        # Return backward compatible stats structure
        return {
            "billing_files_processed": summary["billing_files_processed"],
            "billing_files_skipped": len(all_billing_files) - summary["billing_files_processed"],
            "records_inserted": summary["total_imported"],
        }

    except Exception as e:
        pipeline_end = time.time()
        execution_time = round(pipeline_end - pipeline_start, 2)
        logger.error(f"Execution time: {execution_time} seconds")
        logger.exception("ETL Pipeline failed.")
        raise e
