package com.vitalsync.repo;

import com.vitalsync.domain.VitalReading;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class VitalReadingRepository {

    private final JdbcClient jdbc;

    public VitalReadingRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<VitalReading> MAPPER = (rs, n) -> new VitalReading(
            rs.getLong("id"),
            rs.getString("patient_id"),
            rs.getTimestamp("observed_at").toInstant(),
            rs.getTimestamp("recorded_at").toInstant(),
            rs.getDouble("heart_rate"),
            rs.getDouble("spo2"),
            rs.getDouble("temperature_c"),
            rs.getDouble("respiratory_rate"),
            rs.getDouble("systolic_bp"),
            rs.getDouble("diastolic_bp"),
            (Double) rs.getObject("glucose_mgdl"),
            rs.getBoolean("on_oxygen"),
            rs.getBoolean("alert"),
            (Double) rs.getObject("shock_index"),
            (Double) rs.getObject("pulse_pressure"),
            (Double) rs.getObject("map_mmhg"));

    /** Inserts and returns the generated id. */
    public long insert(VitalReading r) {
        return jdbc.sql("""
                INSERT INTO vital_readings (
                    patient_id, observed_at, heart_rate, spo2, temperature_c,
                    respiratory_rate, systolic_bp, diastolic_bp, glucose_mgdl,
                    on_oxygen, alert, shock_index, pulse_pressure, map_mmhg)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                RETURNING id
                """)
                .params(
                        r.patientId(),
                        Timestamp.from(r.observedAt()),
                        r.heartRate(),
                        r.spo2(),
                        r.temperatureC(),
                        r.respiratoryRate(),
                        r.systolicBp(),
                        r.diastolicBp(),
                        r.glucoseMgdl(),
                        r.onOxygen(),
                        r.alert(),
                        r.shockIndex(),
                        r.pulsePressure(),
                        r.mapMmhg())
                .query(Long.class)
                .single();
    }

    public List<VitalReading> recentForPatient(String patientId, int limit) {
        return jdbc.sql("""
                SELECT * FROM vital_readings
                WHERE patient_id = ?
                ORDER BY observed_at DESC
                LIMIT ?
                """)
                .params(patientId, limit)
                .query(MAPPER)
                .list();
    }

    public VitalReading findById(long id) {
        return jdbc.sql("SELECT * FROM vital_readings WHERE id = ?")
                .param(id)
                .query(MAPPER)
                .optional()
                .orElse(null);
    }

    public long countForPatient(String patientId) {
        return jdbc.sql("SELECT COUNT(*) FROM vital_readings WHERE patient_id = ?")
                .param(patientId)
                .query(Long.class)
                .single();
    }

    public long countSince(Instant since) {
        return jdbc.sql("SELECT COUNT(*) FROM vital_readings WHERE recorded_at >= ?")
                .param(Timestamp.from(since))
                .query(Long.class)
                .single();
    }
}
