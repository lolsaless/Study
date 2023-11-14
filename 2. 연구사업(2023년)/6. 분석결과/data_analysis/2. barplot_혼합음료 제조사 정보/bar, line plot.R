# 필요한 라이브러리를 로드합니다.
library(ggplot2)
library(dplyr)

# 데이터를 생성합니다.
data <- data.frame(
    region = c('GG', 'CB', 'JB', 'GN', 'GW', 'GB', 'JN', 'DG', 'CN', 'GJ', 'BS', 'SJ', 'US', 'IC', 'JJ'),
    Manufacturer = c(20, 9, 8, 7, 6, 5, 5, 4, 3, 2, 2, 2, 2, 1, 1),
    Product = c(67, 39, 21, 16, 7, 39, 13, 8, 3, 11, 5, 7, 2, 1, 2)
)

# Manufacturer를 기준으로 데이터를 정렬합니다.
data <- data %>% arrange(desc(Manufacturer))

# Scale factors를 계산합니다.
sf_main <- max(data$Manufacturer)/20
sf_sec <- 30/ 70  # 주축 범위는 30, 보조축 범위는 80으로 조정하기 위해

# 그래프를 그립니다.
p <- ggplot(data, aes(x = reorder(region, -Manufacturer), group=1)) +
    geom_col(aes(y = Manufacturer * sf_main), fill = "#005B8B", alpha = 0.6, width = 0.5) +
    geom_line(aes(y = Product * sf_sec), color = "#8B0000", size = 1, alpha = 0.4) +
    geom_ribbon(aes(ymin = 0, ymax = Product * sf_sec), fill = "#FF8C00", alpha = 0.4) +
    labs(x = 'Region', y = 'Manufacturer') +
    scale_y_continuous(limits = c(0, 30),  # 주축 범위 조정
                       sec.axis = sec_axis(~./sf_sec, name = "Product", breaks = seq(0, 80, by = 10))) +  # 보조축 범위 및 눈금 조정
    theme_minimal() +
    theme(axis.title.x = element_text(size = 20),
          axis.title.y = element_text(size = 20),
          axis.text.y = element_text(size = 20),
          axis.text.x = element_text(size = 20))

print(p)

# 그래프를 그립니다.
p <- ggplot(data, aes(x = reorder(region, -Manufacturer), group=1)) +
    geom_col(aes(y = Manufacturer * sf_main, fill = "Manufacturer"), alpha = 0.6, width = 0.5) +
    geom_line(aes(y = Product * sf_sec, color = "Product"), size = 1, alpha = 0.4) +
    geom_ribbon(aes(ymin = 0, ymax = Product * sf_sec, fill = "Product"), alpha = 0.4) +
    labs(x = 'Region', y = 'Manufacturer') +
    scale_y_continuous(limits = c(0, 30),  # 주축 범위 조정
                       sec.axis = sec_axis(~./sf_sec, name = "Product", breaks = seq(0, 80, by = 10))) +  # 보조축 범위 및 눈금 조정
    scale_fill_manual(values = c(Manufacturer = "#005B8B", Product = "#FF8C00"), name = "") +
    scale_color_manual(values = c(Product = "#8B0000"), name = "") +
    theme_minimal() +
    theme(axis.title.x = element_text(size = 20, margin = margin(t = 20)),
          axis.title.y = element_text(size = 20, margin = margin(r = 20)),
          axis.text.y = element_text(size = 15),
          axis.text.x = element_text(size = 15, vjust = 1, margin = margin(t = 10)),
          legend.position = "top right")

print(p)

# 그래프를 그립니다.
p <- ggplot(data, aes(x = reorder(region, -Manufacturer), group=1)) +
    geom_col(aes(y = Manufacturer * sf_main, fill = "Manufacturer"), alpha = 0.6, width = 0.5) +
    geom_line(aes(y = Product * sf_sec, color = "Product"), size = 1, alpha = 0.4) +
    geom_ribbon(aes(ymin = 0, ymax = Product * sf_sec, fill = "Product"), alpha = 0.4) +
    labs(x = 'Region', y = 'Manufacturer') +
    scale_y_continuous(limits = c(0, 30),  # 주축 범위 조정
                       sec.axis = sec_axis(~./sf_sec, name = "Product", breaks = seq(0, 80, by = 10))) +  # 보조축 범위 및 눈금 조정
    scale_fill_manual(values = c(Manufacturer = "#005B8B", Product = "#FF8C00"), name = "") +
    scale_color_manual(values = c(Product = "#8B0000"), name = "") +
    theme_minimal() +
    theme(axis.title.x = element_text(size = 20, margin = margin(t = 20)),
          axis.title.y = element_text(size = 20, margin = margin(r = 20)),
          axis.text.y = element_text(size = 15),
          axis.text.x = element_text(size = 15, vjust = 1, margin = margin(t = 10)),
          axis.text.y.right = element_text(margin = margin(l = 20)), # 보조 y 축 라벨과 메인 플롯 사이의 간격 조정
          legend.position = "top right")

print(p)

# 그래프를 그립니다.
p <- ggplot(data, aes(x = reorder(region, -Manufacturer), group=1)) +
    geom_col(aes(y = Manufacturer * sf_main, fill = "Manufacturer"), alpha = 0.6, width = 0.5) +
    geom_line(aes(y = Product * sf_sec, color = "Product"), size = 1, alpha = 0.4) +
    geom_ribbon(aes(ymin = 0, ymax = Product * sf_sec, fill = "Product"), alpha = 0.4) +
    scale_y_continuous(limits = c(0, 30),  # 주축 범위 조정
                       sec.axis = sec_axis(~./sf_sec, breaks = seq(0, 80, by = 10))) +  # 보조축 범위 및 눈금 조정
    scale_fill_manual(values = c(Manufacturer = "#005B8B", Product = "#FF8C00"), name = "") +
    scale_color_manual(values = c(Product = "#8B0000"), name = "") +
    theme_minimal() +
    theme(axis.title.x = element_blank(),  # x축 라벨 제거
          axis.title.y = element_blank(),  # 주 y축 라벨 제거
          axis.title.y.right = element_blank(),  # 보조 y축 라벨 제거
          axis.text.y = element_text(size = 20),
          axis.text.x = element_text(size = 20, vjust = 1, margin = margin(t = 10)),
          axis.text.y.right = element_text(margin = margin(l = 10)), # 보조 y 축 라벨과 메인 플롯 사이의 간격 조정
          legend.position = "top right")

print(p)
