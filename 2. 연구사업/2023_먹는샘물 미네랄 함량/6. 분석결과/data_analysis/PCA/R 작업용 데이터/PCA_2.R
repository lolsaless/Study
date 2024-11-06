library(ggplot2)
library(readxl)
library(ggfortify)
library(FactoMineR)
library(factoextra)

setwd("D:/github/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/PCA")
setwd("C:/Git/Study/2. 연구사업(2023년)/6. 분석결과/data_analysis/PCA")

# Load your data
data <- read_excel("Modified_PCA_B.xlsx")

# PCA에 사용할 수치 데이터 선택
data_pca <- data[, c("Ca", "K", "Na", "Mg", "SiO2", "F", "Cl", "NO3-N", "SO4", "Hardn", "KMn", "pH")]
# 고유한 식별자 생성 (예: 'name_new' 열에 인덱스 추가)
data$name_new_unique <- paste(data$test, seq_len(nrow(data)), sep = "_")

# 고유한 식별자를 rownames로 설정
rownames(data_pca) <- data$name_new_unique

# PCA 수행
pca_result <- PCA(data_pca, scale.unit = TRUE, ncp = 5, graph = FALSE)

# Biplot 생성
fviz_pca_biplot(pca_result, label = "var", geom = c("point", "text"), 
                col.var = "blue", # 변수 색상
                col.ind = "red",  # 개체 색상
                addEllipses = TRUE, # 신뢰구간 타원 추가 (선택적)
                ellipse.type = "confidence", # 타원의 종류
                legend.title = "Groups")
# Biplot 생성 (개체에 test 열의 이름을 표시)
fviz_pca_biplot(pca_result, label = "ind", geom = c("point", "text"), 
                col.var = "blue", # 변수 색상
                col.ind = "red",  # 개체 색상
                label.ind = data$test, # 개체에 표시할 레이블 (test 열의 값)
                addEllipses = TRUE, # 신뢰구간 타원 추가 (선택적)
                ellipse.type = "confidence", # 타원의 종류
                legend.title = "Groups")

# Biplot 생성
fviz_pca_biplot(pca_result, 
                label = "ind", 
                geom.ind = c("point", "text"), 
                geom.var = c("arrow", "text"),
                col.var = "blue", # 변수 색상
                col.ind = "red",  # 개체 색상
                addEllipses = TRUE, # 신뢰구간 타원 추가 (선택적)
                ellipse.type = "confidence", # 타원의 종류
                labelsize = 3, # 레이블 크기
                repel = TRUE, # 레이블 겹침 방지
                label.var = "var", # 변수 레이블
                label.ind = data$name_new) # 개별 점에 사용할 레이블 지정

# Biplot 생성
fviz_pca_biplot(pca_result, 
                label = "ind", 
                geom.ind = c("point", "text"), 
                geom.var = c("arrow", "text"),
                col.var = "blue", # 변수 색상
                col.ind = "red",  # 개체 색상
                addEllipses = TRUE, # 신뢰구간 타원 추가 (선택적)
                ellipse.type = "confidence", # 타원의 종류
                labelsize = 3, # 레이블 크기
                repel = TRUE) # 레이블 겹침 방지
