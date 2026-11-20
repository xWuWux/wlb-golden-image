// WlbJdbcPing.java — pomocniczy program weryfikacji połączenia JDBC dla testu akceptacyjnego 72-pediatria.sh (#271).
// Kompilowany do WlbJdbcPing.class i uruchamiany przez JRE zbundlowane z DBeaver CE (/usr/share/dbeaver-ce/jre/bin/java).
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

public class WlbJdbcPing {
    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("Usage: WlbJdbcPing <url> <user> [password]");
            System.exit(2);
        }
        String url = args[0];
        String user = args[1];
        String password = (args.length >= 3 && !args[2].isEmpty()) ? args[2] : null;
        try {
            Class.forName("org.postgresql.Driver");
            try (Connection conn = (password != null)
                    ? DriverManager.getConnection(url, user, password)
                    : DriverManager.getConnection(url, user, null);
                 Statement stmt = conn.createStatement();
                 ResultSet rs = stmt.executeQuery("SELECT 1")) {
                if (rs.next() && rs.getInt(1) == 1) {
                    System.out.println("WLB_JDBC_OK");
                    System.exit(0);
                } else {
                    System.err.println("Unexpected query result");
                    System.exit(1);
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}
