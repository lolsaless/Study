# R 코드
library(ggplot2)

# 데이터 불러오기
ca_data <- read.xlsx("ca_data.xlsx")

# 대수정규분포 그래프 작성
ggplot(ca_data, aes(x=Ca)) + 
    geom_histogram(aes(y=after_stat(density)), bins=30, fill="skyblue", color="black") +
    geom_density(color="red") + 
    scale_x_log10() +
    labs(title="Log-normal Distribution of Ca Concentration",
         x="Ca Concentration",
         y="Density") +
    theme_minimal()

# 데이터 불러오기
ca_data <- read.xlsx("ca_data.xlsx")

# 대수정규분포 그래프 작성
ggplot(ca_data, aes(x=Ca)) + 
    geom_histogram(aes(y=after_stat(density)), bins=30, fill="skyblue", color="black") +
    geom_density(color="red") + 
    scale_x_log10() +
    labs(title="Log-normal Distribution of Ca Concentration",
         x="Ca Concentration",
         y="Density") +
    theme_minimal()

# 필요한 패키지 불러오기
install.packages(c("ggplot2", "readxl", "moments"))
library(ggplot2)
library(readxl)
library(moments)

# 데이터 불러오기
ca_data <- read_excel("ca_data.xlsx")

# 데이터 로그 변환
log_ca <- log(ca_data$Ca)

# 약간의 노이즈 추가
set.seed(123) # 재현성을 위한 시드 설정
log_ca <- log_ca + rnorm(length(log_ca), mean=0, sd=0.0001)

# 정규 확률 계산
qq <- qqnorm(log_ca, plot.it = FALSE)
qqx <- qq$x
qqy <- qq$y

# K-S 검정 수행
ks_test <- ks.test(log_ca, "pnorm", mean(log_ca), sd(log_ca))

# 그래프 작성
ggplot(data.frame(x = qqx, y = qqy), aes(x=x, y=y)) +
    geom_point(aes(color="blue"), alpha = 0.6) +
    geom_abline(intercept = 0, slope = 1, color = "red") +
    labs(title = paste("Log-normal Distribution of Ca (K-S test Z =", round(ks_test$statistic, 3), ")"),
         x = "ln[Ca] from normal probability",
         y = "ln[Ca] of compiled data") +
    theme_minimal()

# K-S 통계량 출력
ks_test$statistic
