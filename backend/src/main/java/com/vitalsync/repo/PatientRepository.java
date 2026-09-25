package com.vitalsync.repo;

import com.vitalsync.domain.Patient;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class PatientRepository {

    private final JdbcClient jdbc;

    public PatientRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Patient> MAPPER = (rs, n) -> new Patient(
            rs.getString("patient_id"),
            rs.getString("display_name"),
            (Integer) rs.getObject("age"),
            rs.getString("sex"),
            rs.getTimestamp("created_at").toInstant());

    public List<Patient> findAll() {
        return jdbc.sql("SELECT * FROM patients ORDER BY patient_id")
                .query(MAPPER)
                .list();
    }

    public Optional<Patient> findById(String patientId) {
        return jdbc.sql("SELECT * FROM patients WHERE patient_id = ?")
                .param(patientId)
                .query(MAPPER)
                .optional();
    }

    public boolean exists(String patientId) {
        return jdbc.sql("SELECT COUNT(*) FROM patients WHERE patient_id = ?")
                .param(patientId)
                .query(Long.class)
                .single() > 0;
    }

    /**
     * Registers a patient the simulator referenced but that was never seeded,
     * so a demo run cannot fail on a foreign-key violation.
     */
    public void ensureExists(String patientId) {
        jdbc.sql("""
                INSERT INTO patients (patient_id, display_name)
                VALUES (?, ?)
                ON CONFLICT (patient_id) DO NOTHING
                """)
                .params(patientId, "Simulated " + patientId)
                .update();
    }
}
